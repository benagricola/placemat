"""Full prepared composition stays comparable with independent Python judgement."""
from dataclasses import replace
import random

import pytest

from placemat import geometry
from placemat.escapes import judging, Way
from placemat.prepared_escape import prepare
from placemat.score_delta import Delta
from placemat.values import Face, Location, Part
from placemat.layout import Board
from tests.conftest import needs_native
from tests.fixtures import board_geometry
from tests.test_surface_escapes import _shape_board

pytestmark = needs_native


def test_imported_footprint_owned_via_declines_native_without_inventing_pad_identity():
    from tests.fixtures import footprint
    from tests.test_vias_give_way import _via
    parts = [footprint('U1', 10, 10, inst='u1'), footprint('C1', 30, 10, inst='c1')]
    imported = _via('A', 8.6, 10, owner='U1')
    board = Board(board_geometry(parts, copper=(imported,)), keep_going=True)
    board.rect(width=50, height=50)
    for fp in parts:
        board.place(Part(fp.inst), at=fp.location)
    # This used to crash in turn diagnostics before resolve returned.
    plan = board.resolve()
    occ = plan.occupancy
    assert all(number for _, number, *_ in judging(occ).judged())
    before = dict(occ.items), tuple(occ.copper), set(occ.pending)
    occ.lift({'U1'})
    try:
        kernel, reason = prepare(Delta(board, occ, parts[0], plan.links, plan=plan), (0, 90), Face.FRONT)
        assert kernel is None
        assert reason == 'footprint-owned imported via requires the exact Python objective'
    finally:
        occ.unlift({'U1'})
    assert (dict(occ.items), tuple(occ.copper), set(occ.pending)) == before


def _assert_inspection(oracle, ways, walls):
    numbers = {Way.SURFACE: 0, Way.VIA: 1, Way.AWAY: 2, Way.WALLED: 3, None: 4}
    expected = {}
    for ref in sorted(oracle.occ.items):
        if ref in oracle.occ.pending or not oracle.occ.geometry.has_footprint(ref):
            continue
        pads = oracle._lanes_of(ref)[2]
        if len(pads) < oracle.occ.settings.place_escape_min_pads:
            continue
        for number, (net, _, _) in pads.items():
            if net:
                expected[(ref, number)] = numbers[oracle.judge(ref, number)]
    assert {(ref, number): way for ref, number, way in ways} == expected
    assert len(ways) == len(expected)
    regular = {key for key, way in expected.items() if way == 3}
    supplemental = {(r, n) for r, n, *_ in oracle.lanes_walled() + oracle.handoffs_walled()}
    assert set(walls) == regular | supplemental
    assert len(walls) == len(set(walls))


def test_full_prepared_escape_matches_python_counts_and_raw_terms(monkeypatch):
    native = geometry._native
    assert native is not None and hasattr(native, 'PreparedSurface')
    rotations = [0, 37, 90]
    for seed in range(2):
        parts = _shape_board(random.Random(700 + seed))
        board = Board(board_geometry(parts, width=80, height=80), keep_going=True)
        board.rect(width=80, height=80)
        for fp in parts:
            board.place(Part(fp.inst), at=fp.location, rotation=fp.rotation, face=fp.face)
        plan = board.resolve()
        occ, item = plan.occupancy, parts[0]
        original = plan.placement(item.inst)
        occ.lift({item.ref})
        delta = Delta(board, occ, item, plan.links, plan=plan)
        for face in (Face.FRONT, Face.BACK):
            prepared, reason = prepare(delta, rotations, face)
            assert prepared is not None, reason
            for turn, rotation in enumerate(rotations):
                candidate = replace(original, location=Location(30.0000000005, 30), rotation=rotation, face=face)
                terms, crossed, vias, away, walled, ways, walls = prepared.evaluate(candidate, turn, inspect=True)
                view, _, _ = delta._view(candidate)
                monkeypatch.setattr(geometry, '_native', None)
                oracle = judging(view)
                counts = oracle.counts()
                _assert_inspection(oracle, ways, walls)
                raw = delta(candidate)
                monkeypatch.setattr(geometry, '_native', native)
                assert (crossed, vias, away, walled) == (
                    counts['escape_crossed'] - delta._escape_base['escape_crossed'],
                    counts['escape_via'], counts['escape_closed'], counts['escape_walled']), (seed, face, rotation, ways)
                keys = ('airwire', 'crossings', 'link', 'link_over', 'area', 'congestion')
                assert terms == pytest.approx(tuple(raw.terms[k] for k in keys), abs=1e-6)
                assert terms[1] == raw.terms['crossings']
                assert prepared.evaluate(candidate, turn, inspect=True) == (terms, crossed, vias, away, walled, ways, walls)
                assert prepared.evaluate(candidate, turn)[:5] == (terms, crossed, vias, away, walled)


@pytest.mark.parametrize('mode', ['signal', 'quiet', 'handoff', 'lane'])
def test_full_prepared_escape_preserves_rules_holes_bans_and_supplemental_walls(monkeypatch, mode):
    from placemat.occupancy import ban_shape
    from placemat.values import Net, CopperLayer
    from tests.test_escape_findings import _walled_in
    from tests.fixtures import track
    native = geometry._native
    assert native is not None and hasattr(native, 'PreparedSurface')
    parts = _walled_in(0.1)
    if mode == 'handoff':
        parts = parts[:2]  # Original IN membership becomes a board handoff.
    parts[1] = replace(parts[1], npth=((Location(30.9, 30.7), 0.5),))
    copper = [track('IN', 30, 30, 30.2, 30, w=0.15, owner='drawn')] if mode == 'lane' else []
    board = Board(board_geometry(parts, width=80, height=80, copper=copper), keep_going=True)
    board.rect(width=80, height=80)
    board.rule(clearance=0.35, on=Net('IN'), why='fixture pair via rule')
    if mode == 'quiet':
        board.plane(Net('IN'), layers=(CopperLayer.B,))
    for fp in parts:
        board.place(Part(fp.inst), at=fp.location)
    plan = board.resolve()
    occ, item = plan.occupancy, parts[0]
    occ.add_copper([ban_shape('fixture-ban', ((28, 28), (32, 28), (32, 32), (28, 32)), None, ('RING',))])
    if mode == 'lane':
        assert any(s.wire for s in occ.copper if s.net == 'IN')
    original = plan.placement(item.inst)
    occ.lift({item.ref})
    delta = Delta(board, occ, item, plan.links, plan=plan)
    prepared, reason = prepare(delta, [0], original.face)
    assert prepared is not None, reason
    for x in (30, 31.5, 30):
        candidate = replace(original, location=Location(x, 30))
        _, crossed, via, away, walled, ways, walls = prepared.evaluate(candidate, 0, inspect=True)
        view, _, _ = delta._view(candidate)
        monkeypatch.setattr(geometry, '_native', None)
        oracle = judging(view)
        counts = oracle.counts()
        _assert_inspection(oracle, ways, walls)
        if mode == 'lane' and x == 30:
            assert oracle.lanes_walled(), 'fixture must exercise declared copper recheck'
        if mode == 'handoff' and x == 30:
            assert oracle.handoffs_walled(), 'fixture must exercise the handoff recheck'
        monkeypatch.setattr(geometry, '_native', native)
        assert (crossed, via, away, walled) == (
            counts['escape_crossed'] - delta._escape_base['escape_crossed'],
            counts['escape_via'], counts['escape_closed'], counts['escape_walled']), (mode, x, ways)


def _minimal_surface_inputs(native):
    record = ('U1', 'pad', 'S', '1', 1, [(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)], [], False, False)
    candidate = native.PreparedCandidate([((1, 0, 0, 1, 0, 0), [record])])
    delta = native.NativeDelta(native.NativeRatsnest(), ['U1'], [[('S', 'U1', '1', 0, 0)]], ['S'], (4, 3, 5, 0, 2))
    delta.configure_layout([[]], [(0, 0, 1, 1)], None, None, (0, 0, 0, 0))
    fields = [('U1', [('1', 'S', False)], [(0, 1, 0)])]
    nets = [('S', 1, False, 0.2, 0.1, 0.6, 0.3, 0.4, [0])]
    settings = (0.5, 0.5, 0.2, 1, 0.0005, 0.25, True)
    return [candidate, delta, [], ['U1'], [], [[3]], fields, nets, settings]


def test_full_prepared_manifest_refuses_malformed_roles_intent_and_changed_snapshots():
    native = geometry._native
    assert native is not None and hasattr(native, 'PreparedSurface')
    inputs = _minimal_surface_inputs(native)
    surface = native.PreparedSurface(*inputs)
    expected = surface.evaluate(inputs[0], inputs[1], 0, 0, 0)
    for index, value in [(4, [1]), (5, [[]]), (5, [[4]]), (5, [[8]]), (5, [[16]]),
                         (6, []), (6, [('U1', [('2', 'S', False)], [(0, 1, 0)])]),
                         (7, [('S', 1, False, -0.1, 0.1, 0.6, 0.3, 0.4, [0])]),
                         (7, [('S', 1, False, 0.2, 0.1, 0.6, 0.3, 0.4, [])]),
                         (8, (0.5, 0.5, float('nan'), 1, 0.0005, 0.25, True))]:
        changed = list(inputs)
        changed[index] = value
        with pytest.raises(ValueError):
            native.PreparedSurface(*changed)
        assert surface.evaluate(inputs[0], inputs[1], 0, 0, 0) == expected
    replacement = _minimal_surface_inputs(native)
    with pytest.raises(ValueError, match='candidate identity'):
        surface.evaluate(replacement[0], inputs[1], 0, 0, 0)
    with pytest.raises(ValueError, match='delta snapshot'):
        surface.evaluate(inputs[0], replacement[1], 0, 0, 0)
    inputs[1].configure_layout([[]], [(0, 0, 1, 1)], None, None, (0, 0, 0, 0))
    with pytest.raises(ValueError, match='delta snapshot'):
        surface.evaluate(inputs[0], inputs[1], 0, 0, 0)


def test_prepared_moving_pool_requires_exact_metadata_and_island_multiplicity():
    from placemat.prepared_escape import _moving_roles, CONTACT, PATH
    from placemat.occupancy import Shape
    from placemat.values import Box, CopperLayer
    shape = Shape('U1', 'through', frozenset([Face.FRONT]), frozenset([CopperLayer.F]),
                  'S', ((0, 0), (1, 0), (1, 1)), Box(0, 0, 1, 1), '1')
    assert _moving_roles([shape], [(CONTACT, [replace(shape)])]) == [CONTACT]
    assert _moving_roles([shape], [(CONTACT, [replace(shape, wire=True)])]) is None
    assert _moving_roles([shape, replace(shape)], [(PATH, [shape])]) is None
    assert _moving_roles([shape, replace(shape)], [(PATH, [shape, replace(shape)])]) == [PATH, PATH]


def test_full_prepared_cell_copper_carried_and_given_shapes_keep_exact_roles(monkeypatch):
    from placemat.values import Cell, Box
    from tests.test_cell_drops import _geom
    native = geometry._native
    assert native is not None and hasattr(native, 'PreparedSurface')
    board = Board(_geom(), edge_margin=0.5, keep_going=True)
    board.rect(width=80, height=80)
    board.place(Cell('m'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['m']
    own_pad = next(s for s in occ.items['U1'].shapes if s.kind == 'pad' and s.net == 'SIG')
    carried = replace(own_pad, owner='carried-via', kind='through', label='',
                      carried='via-id', points=((own_pad.box.center.x, own_pad.box.center.y),))
    given = replace(carried, owner='given-via', carried='', given='given-id')
    occ.carry('U1', [carried, given])
    original = plan.placement('m')
    occ.lift(['U1'])
    delta = Delta(board, occ, item, plan.links, plan=plan)
    rotations = [0, 37, 143]
    for face in (Face.FRONT, Face.BACK):
        prepared, reason = prepare(delta, rotations, face)
        assert prepared is not None, reason
        cached, reason = prepare(delta, rotations, face, rest_cache=True)
        assert cached is not None, reason
        # Every turn shares validated owner metadata. Moving cell members and
        # carried/given copper are excluded from immutable rest-field reuse.
        for turn, rotation in enumerate(rotations):
            candidate = replace(original, location=Location(25.0000000005, 25.0000000005), rotation=rotation, face=face)
            result = prepared.evaluate(candidate, turn, inspect=True)
            assert cached.evaluate(candidate, turn, inspect=True) == result
            assert cached.surface.cache_usage()[1] >= 1
            _, crossed, via, away, walled, ways, walls = result
            view, _, _ = delta._view(candidate)
            monkeypatch.setattr(geometry, '_native', None)
            oracle = judging(view)
            counts = oracle.counts()
            _assert_inspection(oracle, ways, walls)
            monkeypatch.setattr(geometry, '_native', native)
            assert (crossed, via, away, walled) == (
                counts['escape_crossed'] - delta._escape_base['escape_crossed'],
                counts['escape_via'], counts['escape_closed'], counts['escape_walled']), (face, rotation)


def test_full_prepared_minimum_pad_skip_needs_no_unused_net_class(monkeypatch):
    from placemat.settings import Settings
    from tests.test_surface_escapes import _part_of
    from tests.fixtures import pad
    native = geometry._native
    assert native is not None and hasattr(native, 'PreparedSurface')
    parts = [_part_of('P1', 'p1', [pad('P1', 'p1', 1, 'S', 10, 10, 1, 1)], 10, 10),
             _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 30, 10, 1, 1)], 30, 10)]
    board = Board(board_geometry(parts, width=80, height=80), settings=replace(Settings(), place_escape_min_pads=2))
    board.rect(width=80, height=80)
    for part in parts:
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    occ, item = plan.occupancy, parts[0]
    original = plan.placement('p1')
    occ.lift({'P1'})
    delta = Delta(board, occ, item, plan.links, plan=plan)
    assert delta.native([0], original.face) is not None
    monkeypatch.setattr(type(occ.geometry), 'netclass', lambda *args: pytest.fail('unused escape class lookup'))
    prepared, reason = prepare(delta, [0], original.face)
    assert prepared is not None, reason
    result = prepared.evaluate(original, 0, inspect=True)
    assert result[2:5] == (0, 0, 0)
    assert result[5:] == ([], [])


def test_prepared_pose_must_match_frozen_source_before_native_evaluation():
    from tests.test_score_measures import _two_part_board
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    original = occ._geometry(item).reference
    occ.lift({'C1'})
    delta = Delta(board, occ, item, plan.links, plan=plan)
    prepared, reason = prepare(delta, (rotation for rotation in [original.rotation]), original.face)
    assert prepared is not None, reason
    expected = prepared.evaluate(original, 0)
    for candidate in (replace(original, rotation=original.rotation + 360),
                      replace(original, face=Face.BACK), replace(original, arrangement='different')):
        with pytest.raises(ValueError, match='frozen'):
            prepared.evaluate(candidate, 0)
        assert prepared.evaluate(original, 0) == expected
    for index in (-1, 1, True):
        with pytest.raises(ValueError, match='rotation set'):
            prepared.evaluate(original, index)


def test_diagnostic_stage_profile_preserves_exact_evaluation_and_identity_guards():
    from tests.test_score_search import triangle
    board, item, plan = triangle()
    occ = plan.occupancy
    occ.lift({item.ref})
    delta = Delta(board, occ, item, plan.links, plan=plan)
    prepared, reason = prepare(delta, (0, 37), Face.FRONT)
    assert prepared is not None, reason
    assert hasattr(prepared.surface, 'profile')
    for x, y, turn in [(25, 19, 0), (24.8, 19.2, 1)]:
        expected = prepared.surface.evaluate(prepared.candidate, prepared.scoring, x, y, turn, True)
        actual, timings = prepared.surface.profile(prepared.candidate, prepared.scoring, x, y, turn)
        assert actual == expected
        stages = dict(timings)
        assert set(stages) == {'candidate_us', 'wire_cross_us', 'escape_cross_us', 'records_us',
                               'lanes_us', 'contacts_us', 'classification_total_us', 'aim_us', 'blockers_us',
                               'path_setup_us', 'surface_judge_us', 'supplemental_us', 'layout_us'}
        assert all(value >= 0 for value in stages.values())
        assert stages['lanes_us'] > 0 and stages['surface_judge_us'] > 0
    with pytest.raises(ValueError):
        prepared.surface.profile(prepared.candidate, prepared.scoring, float('nan'), 19, 0)
