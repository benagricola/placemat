"""Exact rest-field reuse remains conservative about geometry and target changes."""
from dataclasses import replace

import pytest

from placemat import geometry
from placemat.layout import Board
from placemat.prepared_escape import prepare
from placemat.score_delta import Delta
from placemat.values import Face, Location, Part
from tests.conftest import needs_native
from tests.fixtures import board_geometry, footprint

pytestmark = needs_native


def scene(quiet=False):
    parts = [footprint('A', 10, 10, inst='a', nets=('N', 'Z')),
             footprint('B', 18, 10, inst='b', nets=('N', 'Z')),
             footprint('T', 75, 55, inst='t', nets=('P', 'Y')),
             footprint('M', 60, 50, inst='m', nets=('P', 'Y'))]
    if quiet:
        parts.insert(-1, footprint('Q', 30, 10, inst='q', nets=('Y', 'OTHER')))
    board = Board(board_geometry(parts, width=100, height=100), keep_going=True)
    board.rect(width=100, height=100)
    if quiet:
        from placemat.values import Net, CopperLayer
        board.plane(Net('Y'), [CopperLayer.B])
    for part in parts:
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    occ = plan.occupancy
    occ.lift({'M'})
    delta = Delta(board, occ, parts[-1], plan.links, plan=plan)
    return board, plan, delta


def test_rest_field_cache_matches_all_per_pad_outcomes_and_rechecks_near_geometry():
    board, plan, delta = scene()
    plain, reason = prepare(delta, (0, 37, 90), Face.FRONT)
    assert plain is not None, reason
    cached, reason = prepare(delta, (0, 37, 90), Face.FRONT, rest_cache=True)
    assert cached is not None, reason
    for x, y in [(60, 50), (11, 11), (12, 10), (24, 10)]:
        for turn, rotation in enumerate((0, 37, 90)):
            pose = replace(delta.occ._geometry(delta.item).reference, location=Location(x, y), rotation=rotation)
            assert cached.evaluate(pose, turn, inspect=True) == plain.evaluate(pose, turn, inspect=True)
            reused, rejudged = cached.surface.cache_usage()
            if x == 60:
                assert reused == 2 and rejudged == 2
            else:
                assert rejudged > 2


def test_rest_cache_rechecks_distant_signal_net_but_not_distant_quiet_net():
    board, plan, delta = scene(quiet=True)
    # A signal net in the moving item is invalidated wherever its pads stand; a quiet net's pad takes no target, so
    # only geometry near it can change its verdict.
    cached, reason = prepare(delta, (0,), Face.FRONT, rest_cache=True)
    assert cached is not None, reason
    plain, reason = prepare(delta, (0,), Face.FRONT)
    assert plain is not None, reason
    pose = replace(delta.occ._geometry(delta.item).reference, location=Location(50, 70))
    assert cached.evaluate(pose, 0, inspect=True) == plain.evaluate(pose, 0, inspect=True)
    assert cached.surface.cache_usage() == (3, 2)


def test_cached_snapshot_refuses_settings_and_rule_source_replacement():
    board, plan, delta = scene()
    cached, reason = prepare(delta, (0,), Face.FRONT, rest_cache=True)
    assert cached is not None, reason
    pose = delta.occ._geometry(delta.item).reference
    board.settings = replace(board.settings, score_escape_closed=board.settings.score_escape_closed + 1)
    with pytest.raises(ValueError, match='settings, geometry or rules changed'):
        cached.evaluate(pose, 0)


@pytest.mark.parametrize('mode', ['signal', 'quiet', 'handoff', 'lane', 'long_chain', 'hole'])
def test_rest_cache_preserves_wall_identities_and_full_chain_invalidation(monkeypatch, mode):
    from placemat.escapes import judging
    from placemat.occupancy import ban_shape
    from placemat.values import Net, CopperLayer
    from tests.test_escape_findings import _walled_in
    from tests.test_prepared_escape import _assert_inspection
    from tests.fixtures import track
    parts = _walled_in(0.1)
    if mode == 'handoff':
        parts = parts[:2]
    moving = footprint('M', 70, 70, inst='m', nets=('P', 'Y'))
    if mode == 'hole':
        moving = replace(moving, npth=((Location(30, 30), 0.5),))
    copper = []
    if mode in ('lane', 'long_chain'):
        end = 70 if mode == 'long_chain' else 30.2
        copper.append(track('IN', 30, 30, end, 30, w=0.15, owner='drawn'))
    board = Board(board_geometry(parts + [moving], width=100, height=100, copper=copper), keep_going=True)
    board.rect(width=100, height=100)
    board.rule(clearance=0.35, on=Net('IN'), why='cache pair via rule')
    if mode == 'quiet':
        board.plane(Net('IN'), [CopperLayer.B])
    for part in parts + [moving]:
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    occ = plan.occupancy
    occ.add_copper([ban_shape('fixture-ban', ((28, 28), (32, 28), (32, 32), (28, 32)), None, ('RING',))])
    occ.lift({'M'})
    delta = Delta(board, occ, moving, plan.links, plan=plan)
    plain, reason = prepare(delta, (0, 37), Face.FRONT)
    assert plain is not None, reason
    cached, reason = prepare(delta, (0, 37), Face.FRONT, rest_cache=True)
    assert cached is not None, reason
    native = geometry._native
    usages = []
    for x, y, turn in [(70, 70, 0), (70, 30, 0), (30, 30, 1), (70, 70, 0)]:
        pose = replace(occ._geometry(moving).reference, location=Location(x, y), rotation=(0, 37)[turn])
        actual = cached.evaluate(pose, turn, inspect=True)
        assert actual == plain.evaluate(pose, turn, inspect=True)
        usages.append(cached.surface.cache_usage())
        view, _, _ = delta._view(pose)
        monkeypatch.setattr(geometry, '_native', None)
        oracle = judging(view)
        counts = oracle.counts()
        _assert_inspection(oracle, actual[5], actual[6])
        monkeypatch.setattr(geometry, '_native', native)
        assert actual[2:5] == (counts['escape_via'], counts['escape_closed'], counts['escape_walled'])
        if mode == 'handoff' and x == 70 and y == 70:
            assert oracle.handoffs_walled()
        if mode == 'lane' and x == 70 and y == 70:
            assert oracle.lanes_walled()
    assert usages[-1] == usages[0], 'candidate repetitions cannot change the baseline cache'
    if mode == 'long_chain':
        assert usages[1][1] > usages[0][1], 'the distant end of fixed copper must invalidate its pad field'


def _cache_record(delta, owner='A'):
    from placemat.escapes import Way, _pads_of, _unconnected
    baseline = delta._escape_delta
    numbers = {None: 4, Way.SURFACE: 0, Way.VIA: 1, Way.AWAY: 2, Way.WALLED: 3}
    pads = _pads_of(delta.occ.items[owner].shapes, owner)
    return owner, [(number, net, _unconnected(delta.occ, owner, number, net),
                    numbers[baseline.ways.get((owner, number))], (-200., -200., 200., 200.),
                    baseline.ways.get((owner, number)) is Way.WALLED, False)
                   for number, (net, _, _) in sorted(pads.items())]


@pytest.mark.parametrize('fault', ['owner', 'duplicate', 'count', 'net', 'unconnected',
                                 'way', 'wall', 'nan', 'window', 'handoff', 'identity'])
def test_rest_cache_rejects_bad_manifest_atomically(fault):
    _, _, delta = scene()
    cached, reason = prepare(delta, (0,), Face.FRONT, rest_cache=True)
    assert cached is not None, reason
    pose = delta.occ._geometry(delta.item).reference
    expected = cached.evaluate(pose, 0, inspect=True)
    usage = cached.surface.cache_usage()
    owner, pads = _cache_record(delta)
    row = list(pads[0])
    bad_owner = owner
    if fault == 'owner':
        bad_owner = 'missing'
    elif fault == 'count':
        pads = pads[:-1]
    elif fault == 'net':
        row[1] = 'OTHER'
    elif fault == 'unconnected':
        row[2] = not row[2]
    elif fault == 'way':
        row[3] = 5
    elif fault == 'wall':
        row[3], row[5] = 3, False
    elif fault == 'nan':
        row[4] = (float('nan'), -200., 200., 200.)
    elif fault == 'window':
        row[4] = (9., 9., 11., 11.)
    elif fault == 'handoff':
        row[6] = True
    if fault != 'count':
        pads[0] = tuple(row)
    records = [(owner, _cache_record(delta)[1]), (bad_owner, pads)]
    if fault not in ('duplicate', 'identity'):
        records[0] = _cache_record(delta, 'B')
    candidate = cached.candidate
    if fault == 'identity':
        _, _, another = scene()
        other, reason = prepare(another, (0,), Face.FRONT)
        assert other is not None, reason
        candidate = other.candidate
    with pytest.raises(ValueError, match='rest cache'):
        cached.surface.configure_rest_cache(candidate, cached.scoring, records)
    assert cached.evaluate(pose, 0, inspect=True) == expected
    assert cached.surface.cache_usage() == usage


def test_rest_cache_4000_candidates_match_independent_python(monkeypatch):
    """Every pad identity and signed term is checked, including cache hits."""
    import random
    from placemat.escapes import judging
    from tests.test_prepared_escape import _assert_inspection
    _, _, delta = scene(quiet=True)
    rotations = (0, 37, 90, 143)
    native = geometry._native
    rng = random.Random(20261007)
    reused = rejudged = 0
    for face in (Face.FRONT, Face.BACK):
        plain, reason = prepare(delta, rotations, face)
        assert plain is not None, reason
        cached, reason = prepare(delta, rotations, face, rest_cache=True)
        assert cached is not None, reason
        for index in range(2000):
            turn = index % len(rotations)
            pose = replace(delta.occ._geometry(delta.item).reference,
                           location=Location(rng.uniform(5, 90), rng.uniform(5, 90)),
                           rotation=rotations[turn], face=face)
            actual = cached.evaluate(pose, turn, inspect=True)
            assert actual == plain.evaluate(pose, turn, inspect=True), (face, index)
            hits, misses = cached.surface.cache_usage()
            reused += hits
            rejudged += misses
            view, _, _ = delta._view(pose)
            with monkeypatch.context() as forced:
                forced.setattr(geometry, '_native', None)
                oracle = judging(view)
                counts = oracle.counts()
                _assert_inspection(oracle, actual[5], actual[6])
                raw = delta(pose)
            assert geometry._native is native
            assert actual[1:5] == (
                counts['escape_crossed'] - delta._escape_base['escape_crossed'],
                counts['escape_via'], counts['escape_closed'], counts['escape_walled'])
            keys = ('airwire', 'crossings', 'link', 'link_over', 'area', 'congestion')
            assert actual[0] == pytest.approx(tuple(raw.terms[key] for key in keys), abs=1e-6)
            assert actual[0][1] == raw.terms['crossings']
            if (index + 1) % 500 == 0:
                print(f'cache parity face={face} candidates={index + 1} reused={reused} rejudged={rejudged}', flush=True)
    assert reused > 0 and rejudged > 0
