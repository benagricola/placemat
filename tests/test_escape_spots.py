"""The one-score search scores every candidate on the run score's terms but the escape grades, and gives the escape
grades and the walled check to the best `place.escape_spots` by that (D25)."""
from dataclasses import replace
import math

import pytest

from placemat import geometry, placer, settings as S
from placemat.score_delta import Delta
from placemat.score_search import MSTScorer
from placemat.values import Face, Location
from tests.test_score_search import triangle


def _native_available():
    return hasattr(geometry._native, 'NativeDeltaScoring') and hasattr(geometry._native.NativeDeltaScoring, 'full')


def _scan(board, item, plan, *, spots, prune=True, pick=None, native=True, monkeypatch):
    board.settings = replace(board.settings, place_escape_spots=spots)
    occ = plan.occupancy
    hint = occ._geometry(item).reference
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan, prune=prune)
    graded = []
    original = Delta._escape_change
    monkeypatch.setattr(Delta, '_escape_change', lambda self, *a, **kw: (graded.append(1), original(self, *a, **kw))[1])
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    result = placer.scan(occ, item, hint, 8.0, 0.25, rotations=(0, 90), clearance=board.geometry.default_clearance,
                         score=scoring, pick=pick)
    prepared = scoring._native.get(((0, 90), Face.FRONT)) if native else None
    escaped = len(graded) + (prepared.escaped if prepared is not None else 0)
    return result, escaped, scoring


@pytest.mark.parametrize('native', [False, True])
def test_escape_grades_only_for_the_best_few(monkeypatch, native):
    if native and not _native_available():
        pytest.skip('native partial scoring unavailable')
    board, item, plan = triangle(True)
    result, escaped, _ = _scan(board, item, plan, spots=2, native=native, monkeypatch=monkeypatch)
    assert result.chosen is not None and result.walled == 0
    # two reads of the best (the refinement's seeds, the choice), each walking to 2 that wall none
    assert 0 < escaped <= 4 < result.tried // 10, (escaped, result.tried)


@pytest.mark.parametrize('native', [False, True])
def test_escape_spots_at_a_large_value_equals_full_scoring_of_every_candidate(monkeypatch, native):
    if native and not _native_available():
        pytest.skip('native partial scoring unavailable')
    runs = {}
    for mode in ('few', 'all'):
        board, item, plan = triangle(True)
        if mode == 'few':
            result, escaped, _ = _scan(board, item, plan, spots=10 ** 6, native=native, monkeypatch=monkeypatch)
        else:       # a draw reads every candidate, so every one is scored in full
            result, escaped, _ = _scan(board, item, plan, spots=8, prune=False, pick=lambda rows: rows[0],
                                       native=native, monkeypatch=monkeypatch)
        runs[mode] = (result.chosen, result.walled, result.score, escaped)
        monkeypatch.undo()
    assert runs['few'][:3] == runs['all'][:3]
    assert runs['few'][3] == runs['all'][3], runs


@pytest.mark.parametrize('native', [False, True])
def test_walled_best_candidate_is_dropped_for_the_next(monkeypatch, native):
    from placemat.layout import Board
    from placemat.occupancy import ban_shape
    from placemat.settings import Settings
    from placemat.values import Part
    from tests.fixtures import board_geometry, pad, track
    from tests.test_surface_escapes import _part_of, _round_pad
    if native and not _native_available():
        pytest.skip('native partial scoring unavailable')
    item = _part_of('P1', 'p1', [_round_pad('P1', 'p1', 1, 'S', 30, 30, 0.5)], 30, 30)
    target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, 30, 0.5, 0.5)], 10, 30)
    ring = []
    for index in range(96):
        angle = 2 * math.pi * index / 96
        x, y = 30 + 1.3 * math.cos(angle), 30 + 1.3 * math.sin(angle)
        ring.append(track('Z', x, y, x + 0.001, y, w=0.1))
    cfg = replace(Settings(), cleanup_enabled=False, score_escape_closed=0.0, score_escape_via=0.0,
                  score_escape_crossed=0.0, score_congestion=0.0, place_escape_spots=1)
    board = Board(board_geometry([item, target], width=60, height=60, copper=ring), keep_going=True, settings=cfg)
    board.rect(width=60, height=60)
    for part in [item, target]:
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    occ = plan.occupancy
    occ.add_copper([ban_shape('via exclusion', ((28, 28), (32, 28), (32, 32), (28, 32)), None, ('Z',))])
    hint = occ._geometry(item).reference
    occ.lift({'P1'})
    scoring = MSTScorer(board, occ, item, plan=plan, prune=True)
    inside = scoring(hint)
    nearer = scoring.scan(hint)[1]
    assert inside[0] > 0 and nearer < scoring.scan(replace(hint, location=Location(34, 30)))[1], \
        'fixture must make the walled pose first by the partial cost'
    taken = []
    full = scoring.full
    monkeypatch.setattr(scoring, 'full', lambda p, **kw: (taken.append(p.location), full(p, **kw))[1])
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', native)
    result = placer.scan(occ, item, hint, 4, 2, rotations=(0,), score=scoring,
                         within=lambda x, y: x >= 30 and y == 30)
    assert result.chosen.location == Location(34, 30)
    assert result.walled == 0
    assert taken[0] == Location(30, 30) and Location(34, 30) in taken


@pytest.mark.parametrize('crossing', [False, True])
def test_partial_cost_is_the_full_cost_less_the_escape_grades(crossing):
    """Python and native partial costs agree, and differ from the full cost by the escape grades alone."""
    if not _native_available():
        pytest.skip('native partial scoring unavailable')
    board, item, plan = triangle(crossing)
    occ = plan.occupancy
    occ.lift({item.ref})
    scoring = MSTScorer(board, occ, item, plan=plan)
    native = scoring.native((0, 90), Face.FRONT)
    assert native is not None, scoring.refusals
    for x, y, turn in [(25, 19, 0), (24.8, 19.2, 1), (20, 25, 0), (30, 25, 1)]:
        candidate = replace(occ._geometry(item).reference, location=Location(x, y), rotation=(0, 90)[turn])
        change = scoring.delta(candidate)
        partial = scoring.scan(candidate)
        assert partial[0] == placer.PARTIAL
        assert partial[1] == pytest.approx(change.total - change.terms['escape_closed'] - change.terms['escape_via'],
                                           abs=1e-9)
        assert native.partial_cost(x, y, turn) == pytest.approx(partial[1], abs=1e-9)
        native.escapes = False
        assert native.evaluate(x, y, turn) == (pytest.approx(partial[1], abs=1e-9), placer.PARTIAL)
        assert scoring.full(candidate) == (change.walled, pytest.approx(change.total, abs=1e-9))


def test_escape_spots_is_a_count_of_at_least_one():
    assert S.Settings().place_escape_spots == 8
    assert S.Settings().place_search_wire == 'mst'
    with pytest.raises(S.SettingsError):
        S._validate('place_escape_spots', 0, 'test')
    S._validate('place_escape_spots', 1, 'test')


def test_walk_counts_walls_beyond_the_lifted_boards(monkeypatch):
    """A lifted board that walls pads already: a candidate scored in full at that count walls none of its own and
    counts toward `place.escape_spots`; one past it is passed over for the next in the partial order."""
    board, item, plan = triangle(False)
    occ = plan.occupancy
    hint = occ._geometry(item).reference
    occ.lift({item.ref})
    first = (hint.location.x, hint.location.y)

    class Scorer:
        spots, walled_base, best = 2, 3, [math.inf]
        asked = []

        def scan(self, p):
            return placer.PARTIAL, math.hypot(p.location.x - first[0], p.location.y - first[1]) + p.rotation

        def full(self, p, python=False):
            self.asked.append(p)
            near = (p.location.x, p.location.y) == first and p.rotation == 0
            return self.walled_base + near, self.scan(p)[1] - 100 * near

        def __call__(self, p):
            raise AssertionError('a scan asks scan and full only')

    scorer = Scorer()
    monkeypatch.setattr(placer, 'NATIVE_SWEEP', False)
    result = placer.scan(occ, item, hint, 0.5, 0.25, rotations=(0, 90), clearance=board.geometry.default_clearance,
                         score=scorer)
    assert (scorer.asked[0].location.x, scorer.asked[0].location.y, scorer.asked[0].rotation) == (*first, 0)
    assert len(scorer.asked) == 3                       # the walled one, then two at the lifted board's count
    assert result.walled == 3 and result.chosen != scorer.asked[0]
