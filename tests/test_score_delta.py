"""Exact changes of the common placement objective."""
import math
import random

import pytest

from placemat.ratsnest import Anchor, mst, mst_change


def _length(edges):
    return sum(math.hypot(e.a.x - e.b.x, e.a.y - e.b.y) for e in edges)


def _identities(edges):
    return {frozenset((e.a, e.b)) for e in edges}


@pytest.mark.parametrize("backend", ["python", "native"])
def test_mst_addition_matches_whole_tree_including_ties_and_empty_rest(backend, monkeypatch):
    from placemat import geometry
    if backend == "python":
        monkeypatch.setattr(geometry, "_native", None)
    elif geometry._native is None:
        pytest.skip("native module unavailable")
    rng = random.Random(3)
    for trial in range(200):
        rest = [Anchor("R%d" % i, "1", rng.randrange(20), rng.randrange(20)) for i in range(rng.randrange(30))]
        new = [Anchor("N", str(k), rng.randrange(20), rng.randrange(20)) for k in range(rng.randint(1, 6))]
        previous = mst("n", rest)
        added, dropped, change = mst_change(rest, previous, new, net="n")
        whole = mst("n", rest + new)
        assert abs(change - (_length(whole) - _length(previous))) < 1e-9
        assert _identities(whole) == (_identities(previous) - _identities(dropped)) | _identities(added)


def test_mst_addition_can_reduce_wire():
    rest = [Anchor("R1", "1", 0, 0), Anchor("R2", "1", 1, 0), Anchor("R3", "1", 0.5, math.sqrt(3) / 2)]
    new = [Anchor("N", "1", 0.5, math.sqrt(3) / 6)]
    added, dropped, change = mst_change(rest, mst("n", rest), new)
    assert change < 0
    assert len(added) == 3 and len(dropped) == 2


def test_python_escape_delta_matches_whole_and_carries_unpriced_wall_evidence():
    from dataclasses import replace
    from placemat import score
    from placemat.score_delta import Delta
    from placemat.values import Location
    from tests.fixtures import board_geometry, pad, track
    from tests.fixtures import placed as _placed
    from tests.test_surface_escapes import _part_of, _round_pad
    main = _part_of('P1', 'p1', [_round_pad('P1', 'p1', 1, 'S', 30, 30, 1.0)], 30, 30)
    target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, 30, 1.0, 1.0)], 10, 30)
    ring = []
    for i in range(96):
        angle = 2 * math.pi * i / 96
        x, y = 30 + 1.3 * math.cos(angle), 30 + 1.3 * math.sin(angle)
        ring.append(track('Z', x, y, x + 0.001, y, w=0.1))
    board, plan = _placed(board_geometry([main, target], copper=ring))
    occ = plan.occupancy
    original = plan.placement('p1')
    occ.lift({'P1'})
    before = score.whole(board, occ, plan)
    baseline_wall = score._incremental(board, occ, plan)['findings'].get('escape_walled', 0)
    delta = Delta(board, occ, main, plan.links, plan=plan)
    counts = []
    for candidate in (original, replace(original, location=Location(30, 20)), original):
        delta = Delta(board, occ, main, plan.links, plan=plan)
        change = delta(candidate, prune_above=-math.inf)
        assert score.whole(board, occ, plan) == before
        occ.commit(main, candidate)
        after = score.whole(board, occ, plan)
        wall = score._incremental(board, occ, plan)['findings'].get('escape_walled', 0)
        for term in ('escape_crossed', 'escape_closed', 'escape_via'):
            assert change.terms[term] == pytest.approx(after[term] - before[term])
        assert change.walled == wall
        assert change.walled_change == wall - baseline_wall
        assert 'escape_walled' not in change.terms
        counts.append(wall)
        occ.lift({'P1'})
    assert counts[0] > counts[1] and counts[2] == counts[0]
    occ.commit(main, original)


def test_new_nearer_target_can_reduce_a_remote_pads_escape_price():
    from dataclasses import replace
    from placemat import score
    from placemat.escapes import Way, judging
    from placemat.score_delta import Delta
    from placemat.values import CopperLayer, Location, Net
    from tests.fixtures import footprint
    from tests.test_escape_findings import _walled_in
    from tests.test_surface_escapes import _via_only_board
    parts = _walled_in(0.1)
    ring = parts[1]
    parts[1] = replace(ring, pads=tuple(p for p in ring.pads
        if not (p.box.center.x > 30.5 and abs(p.box.center.y - 30) < 0.1)))
    parts[2] = footprint('T1', 10, 30, inst='t1', nets=('IN', 'Z'))
    moving = footprint('N1', 50, 50, inst='n1', nets=('IN', 'Z'))
    board = _via_only_board(parts + [moving])
    for y in (29.25, 30.75):
        board.track(Net('Z'), [Location(31.9, y), Location(34, y)], layer=CopperLayer.F,
                    width=0.2, why='fixture gap walls')
    plan = board.resolve()
    occ = plan.occupancy
    occ.lift({'N1'})
    assert judging(occ).judge('U9', '1') is Way.AWAY
    before = score.whole(board, occ, plan)
    delta = Delta(board, occ, moving, plan.links, plan=plan)
    candidate = replace(plan.placement('n1'), location=Location(40, 30))
    change = delta(candidate)
    occ.commit(moving, candidate)
    assert judging(occ).judge('U9', '1') is Way.SURFACE
    after = score.whole(board, occ, plan)
    assert change.terms['escape_closed'] == after['escape_closed'] - before['escape_closed'] < 0


def test_candidate_escape_view_reuses_proved_trees_without_whole_mst_or_shared_cache_mutation(monkeypatch):
    from placemat import ratsnest, score
    from placemat.score_delta import Delta
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(30, 30))
    plan = board.resolve()
    occ = plan.occupancy
    item = plan._items[plan.steps[0].item]
    occ.lift({'U1'})
    delta = Delta(board, occ, item, plan.links, plan=plan)
    before = score.whole(board, occ, plan)
    anchors = dict(occ.ratsnest()._anchors)
    def forbidden(*args, **kwargs):
        raise AssertionError('candidate rebuilt a whole MST')
    monkeypatch.setattr(ratsnest, 'mst', forbidden)
    change = delta(plan.placement('u1'))
    assert math.isfinite(change.total)
    assert occ.ratsnest()._anchors == anchors
    # Compare the complete candidate oracle outside the guarded hot path.
    monkeypatch.undo()
    occ.commit(item, plan.placement('u1'))
    after = score.whole(board, occ, plan)
    assert change.terms == pytest.approx({k: after[k] - before[k] for k in change.terms}, abs=1e-6)
    with pytest.raises(ValueError, match='remain lifted'):
        delta(plan.placement('u1'))
    with pytest.raises(ValueError, match='remain lifted'):
        delta.native([0], plan.placement('u1').face)


@pytest.mark.parametrize('moving_ref', ['A0', 'M0', 'Z0'])
def test_sparse_candidate_view_preserves_raw_nearest_ties_and_multiland_anchor_identity(moving_ref):
    from dataclasses import replace
    from placemat import score
    from placemat.escapes import judging
    from placemat.score_delta import Delta
    from placemat.values import Face, Location
    from tests.fixtures import board_geometry, pad
    from tests.fixtures import placed as _placed
    from tests.test_surface_escapes import _part_of
    def part(ref, x, y):
        return _part_of(ref, ref.lower(), [pad(ref, ref.lower(), 1, 'S', x, y, 0.3, 0.3)], x, y)
    parts = [part('B0', 28, 30), part('P0', 30, 30), part('Y0', 32, 30)]
    lands = [replace(pad(moving_ref, 'm', 1, 'S', 29.75, 28, 0.2, 0.3), anchor=Location(30, 28)),
             replace(pad(moving_ref, 'm', 1, 'S', 30.25, 28, 0.2, 0.3, face=Face.BACK), anchor=Location(30, 28))]
    moving = _part_of(moving_ref, 'm', lands, 30, 28)
    board, plan = _placed(board_geometry(parts + [moving]))
    occ = plan.occupancy
    occ.lift({moving_ref})
    delta = Delta(board, occ, moving, plan.links, plan=plan)
    from placemat import geometry
    kernel = None if geometry._native is None else delta.native([plan.placement('m').rotation], plan.placement('m').face)
    if geometry._native is not None:
        assert kernel is not None and hasattr(kernel, 'aim')
    before = score.whole(board, occ, plan)
    baseline_anchors = dict(occ.ratsnest()._anchors)
    baseline_mirror = occ.ratsnest().mirror
    observed = []
    original = delta._escape_change
    def check(view, geometries, copper):
        rn = view.ratsnest()
        assert len([a for a in rn._anchors['S'] if a.ref == moving_ref]) == 1
        assert [(a.ref, a.number) for a in rn._anchors['S']] == sorted((a.ref, a.number) for a in rn._anchors['S'])
        observed.append(judging(view)._aim('P0', '1', 'S', Location(30, 30)))
        return original(view, geometries, copper)
    delta._escape_change = check
    first = delta(plan.placement('m'))
    assert delta(plan.placement('m')) == first
    assert observed == [(0.0, -2.0) if moving_ref == 'A0' else (-2.0, 0.0)] * 2
    if kernel is not None:
        candidate = plan.placement('m')
        expected = observed[0]
        assert kernel.aim(candidate.location.x, candidate.location.y, 0,
                          'S', 'P0', '1', (30, 30)) == expected
        # Sub-nm raw distance breaks an otherwise quantized/MST tie. Rest
        # anchors and stable ref order must not override that strict change.
        for shift in [-0.0000000005, 0.0000000005, 0.0]:
            candidate = replace(plan.placement('m'), location=Location(30, 28 + shift))
            view, _, _ = delta._view(candidate)
            aim = judging(view)._aim('P0', '1', 'S', Location(30, 30))
            assert kernel.aim(candidate.location.x, candidate.location.y, 0,
                              'S', 'P0', '1', (30, 30)) == aim
    assert occ.ratsnest()._anchors == baseline_anchors and occ.ratsnest().mirror is baseline_mirror
    occ.commit(moving, plan.placement('m'))
    after = score.whole(board, occ, plan)
    assert first.terms == pytest.approx({k: after[k] - before[k] for k in first.terms}, abs=1e-6)


def test_affected_escape_snapshot_rechecks_exact_window_and_skips_disjoint_other_nets():
    from dataclasses import replace
    from placemat.escapes import EscapeDelta, Way, judging
    from placemat.score_delta import Delta
    from placemat.values import Location
    from tests.fixtures import pad
    from tests.test_escape_findings import _walled_in
    from tests.test_surface_escapes import _part_of, _via_only_board
    moving = _part_of('B1', 'b1', [pad('B1', 'b1', 1, 'Z', 10, 10, 6, 6)], 10, 10)
    remote = [_part_of(ref, ref.lower(), [pad(ref, ref.lower(), 1, 'Q', x, 40, 0.3, 0.3)], x, 40)
              for ref, x in [('D1', 40), ('D2', 45)]]
    board = _via_only_board(_walled_in(1.0) + [moving] + remote)
    plan = board.resolve()
    occ = plan.occupancy
    occ.lift({'B1'})
    delta = Delta(board, occ, moving, plan.links, plan=plan)
    snapshot = delta._escape_delta
    assert snapshot.base.judge('U9', '1') is Way.SURFACE
    assert not snapshot.base.lane_check('U9', '1')[1]  # only the exact path gets out
    candidate = replace(plan.placement('b1'), location=Location(30, 30))
    view, geometries, copper = delta._view(candidate)
    expected = {key: len(value) for key, value in judging(view).found().items()}
    assert judging(view).judge('U9', '1') is Way.WALLED
    before = snapshot.counts.copy()
    for native in (False, True, False):
        from placemat import geometry
        if native and not hasattr(geometry._native, 'surface_judge'):
            continue
        actual, rejudged = snapshot.change(view, geometries, copper, native=native)
        assert actual == expected
        assert rejudged < len(snapshot.ways) + 1  # disjoint Q pads retain their proved baseline
    assert snapshot.counts == before and not snapshot.base._lane_cache.get('B1')
    occ.commit(moving, candidate)
    with pytest.raises(ValueError, match='remain lifted'):
        snapshot.change(view, geometries, copper)
    with pytest.raises(ValueError, match='lifted'):
        EscapeDelta(occ, {'B1'})


def test_native_signed_escape_crossings_match_whole_including_cancelled_joint_changes():
    from placemat import geometry
    from placemat.ratsnest import Ratsnest, prices_of
    from placemat.settings import Settings
    module = geometry._native
    if not hasattr(getattr(module, 'NativeDelta', None), 'escape_cross'):
        pytest.skip('native signed escape kernel not built')
    cfg = Settings()
    rng = random.Random(43)
    rest = {net: [Anchor(ref, net, rng.uniform(-3, 3), rng.uniform(-3, 3))
                  for ref in ('U1', 'U2', 'U3')] for net in ('a', 'b', 'c')}
    def whole(nodes):
        rn = Ratsnest()
        for net, points in nodes.items():
            rn.set_net(net, points)
        return rn
    base = whole(rest)
    mirror = module.NativeRatsnest()
    rn = Ratsnest(mirror=mirror, prices=prices_of(cfg))
    for net, points in rest.items():
        rn.set_net(net, points)
    origin = [(net, 'N', net, rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5)) for net in rest]
    kernel = module.NativeDelta(mirror, ['N'], [origin], list(rest),
        (cfg.score_crossing, cfg.score_impedance, cfg.score_crossing_pair_net,
         cfg.score_crossing_plane, cfg.score_pair_crossing))
    values = []
    for _ in range(100):
        x, y = rng.uniform(-4, 4), rng.uniform(-4, 4)
        nodes = {net: points + [Anchor('N', pad, px + x, py + y)]
                 for net, _, pad, px, py in origin for points in [rest[net]]}
        candidate = whole(nodes)
        for depth in (0.0, 0.25, 1.0, 5.0):
            expected = candidate.crossed_pairs(depth) - base.crossed_pairs(depth)
            assert kernel.escape_cross(x, y, 0, depth) == expected
            values.append(expected)
    assert min(values) < 0 < max(values)
    for depth in (-1.0, math.inf, math.nan):
        with pytest.raises(ValueError, match='escape'):
            kernel.escape_cross(0.0, 0.0, 0, depth)


def test_mst_addition_refuses_prejoined_copper_clusters():
    rest = [Anchor("R1", "1", 0, 0), Anchor("R2", "1", 1, 0)]
    previous = mst("n", rest, joined=[(0, 1)])
    with pytest.raises(ValueError, match="unjoined"):
        mst_change(rest, previous, [Anchor("N", "1", 2, 0)], net="n")


@pytest.mark.parametrize('crossing,plane', [(4.0, 0.0), (4.0, 0.75), (0.0, 0.0)])
def test_native_wire_and_crossings_match_exact_whole_changes(crossing, plane):
    from dataclasses import replace
    from placemat import geometry, score
    from placemat.ratsnest import Ratsnest, crossings, prices_of
    from placemat.settings import Settings
    native = geometry._native
    if native is None or not hasattr(native, 'NativeDelta'):
        pytest.skip('NativeDelta not built')
    cfg = replace(Settings(), score_crossing=crossing, score_crossing_plane=plane)
    kinds = {'a': 2, 'b': 2, 'c': 1, 'd': 0, 'p': 3}
    partners = {'a': 'b', 'b': 'a'}
    rn = Ratsnest(kinds, native.NativeRatsnest(), partners, prices_of(cfg))
    rng = random.Random(12)
    rest = {net: [Anchor('%s%d' % (net, i), '1', rng.randrange(20), rng.randrange(20)) for i in range(8)] for net in kinds}
    for net, nodes in rest.items():
        rn.set_net(net, nodes)
    origins = [(net, 'N', str(i), rng.uniform(-1, 1), rng.uniform(-1, 1)) for i, net in enumerate(['a', 'a', 'b', 'c', 'd', 'p'])]
    delta = native.NativeDelta(rn.mirror, ['N'], [origins], ['a', 'b', 'c', 'd'],
                              (cfg.score_crossing, cfg.score_impedance, cfg.score_crossing_pair_net,
                               cfg.score_crossing_plane, cfg.score_pair_crossing))
    def measured(nodes):
        edges = [edge for net, anchors in nodes.items() for edge in mst(net, anchors)]
        _, _, classes = crossings(edges, kinds, partners)
        wire = sum(_length(mst(net, anchors)) for net, anchors in nodes.items() if net != 'p')
        impedance = _length(mst('c', nodes['c']))
        terms = score.terms({'crossings': classes, 'airwire_mm': wire, 'airwire_impedance_mm': impedance}, cfg)
        return terms['airwire'], terms['crossings']
    before = measured(rest)
    from placemat.score_delta import Delta
    twin = object.__new__(Delta)
    twin.kinds, twin.partners = kinds, partners
    twin.old = {net: mst(net, anchors) for net, anchors in rest.items()}
    twin.cross_prices = (cfg.score_crossing, cfg.score_crossing * cfg.score_impedance,
                         cfg.score_crossing * cfg.score_crossing_pair_net,
                         cfg.score_crossing * cfg.score_crossing_plane, cfg.score_pair_crossing)
    for _ in range(500):
        x, y = rng.uniform(0, 20), rng.uniform(0, 20)
        nodes = {net: list(anchors) for net, anchors in rest.items()}
        for net, ref, number, px, py in origins:
            nodes[net].append(Anchor(ref, number, px + x, py + y))
        after = measured(nodes)
        changed = {}
        for net, anchors in nodes.items():
            new_tree = mst(net, anchors)
            previous = _identities(twin.old[net])
            current = _identities(new_tree)
            changed[net] = (new_tree, [e for e in new_tree if frozenset((e.a, e.b)) not in previous],
                            [e for e in twin.old[net] if frozenset((e.a, e.b)) not in current])
        assert twin._crossing_change(changed) == pytest.approx(after[1] - before[1], abs=1e-8)
        change = delta.wire_cross(x, y, 0)
        assert change == pytest.approx((after[0] - before[0], after[1] - before[1]), abs=1e-8)


def test_native_mst_change_on_large_net_stays_sparse():
    import time
    from placemat import geometry
    from placemat.ratsnest import Ratsnest
    native = geometry._native
    if native is None or not hasattr(native, 'NativeDelta'):
        pytest.skip('NativeDelta not built')
    rng = random.Random(7)
    rest = [Anchor('R%d' % i, '1', rng.uniform(0, 30), rng.uniform(0, 30)) for i in range(400)]
    rn = Ratsnest(mirror=native.NativeRatsnest())
    rn.set_net('n', rest)
    pads = [('n', 'N', str(i), rng.uniform(0, 2), rng.uniform(0, 2)) for i in range(10)]
    delta = native.NativeDelta(rn.mirror, ['N'], [pads], ['n'], (4.0, 3.0, 5.0, 0.0, 2.0))
    for _ in range(10):
        delta.wire_cross(10.0, 10.0, 0)
    began = time.perf_counter()
    for i in range(200):
        delta.wire_cross(10.0 + i / 1000, 10.0, 0)
    elapsed = (time.perf_counter() - began) / 200
    assert elapsed < 200e-6, '%.1f us per large-net candidate' % (elapsed * 1e6)


def test_native_delta_validates_its_boundary_and_preserves_empty_net_kind():
    from placemat import geometry
    native = geometry._native
    if native is None or not hasattr(native, 'NativeDelta'):
        pytest.skip('NativeDelta not built')
    settings = (4.0, 3.0, 5.0, 0.0, 2.0)
    rn = native.NativeRatsnest()
    rn.set_kind('n', 1)  # every pad of this impedance net belongs to the lifted item
    pads = [('n', 'N', '1', 0.0, 0.0), ('n', 'N', '2', 1.0, 0.0)]
    delta = native.NativeDelta(rn, ['N'], [pads], ['n'], settings)
    assert delta.wire_cross(0.0, 0.0, 0) == pytest.approx((3.0, 0.0))
    with pytest.raises(ValueError, match='finite'):
        delta.wire_cross(float('nan'), 0.0, 0)
    with pytest.raises(ValueError, match='finite'):
        native.NativeDelta(rn, ['N'], [[('n', 'N', '1', float('inf'), 0.0)]], ['n'], settings)
    with pytest.raises(ValueError, match='turn'):
        delta.wire_cross(0.0, 0.0, 9)
    with pytest.raises(ValueError, match='representable'):
        delta.wire_cross(1e300, 0.0, 0)
    with pytest.raises(ValueError, match='representable'):
        native.NativeDelta(rn, ['N'], [[('n', 'N', '1', 1e300, 0.0)]], ['n'], settings)
    rn.set_kind('n', 9)
    with pytest.raises(ValueError, match='kind'):
        native.NativeDelta(rn, ['N'], [pads], ['n'], settings)


def test_native_delta_refuses_disconnected_or_invalid_rest_edges():
    from placemat import geometry
    native = geometry._native
    if native is None or not hasattr(native, 'NativeDelta'):
        pytest.skip('NativeDelta not built')
    rn = native.NativeRatsnest()
    anchors = [('A', '1', 0.0, 0.0), ('B', '1', 1.0, 0.0), ('C', '1', 2.0, 0.0)]
    edge = ('A', '1', 0.0, 0.0, 'B', '1', 1.0, 0.0)
    pads = [[('n', 'N', '1', 0.0, 1.0)]]
    rn.set_net('n', anchors, [edge, edge])
    with pytest.raises(ValueError, match='acyclic'):
        native.NativeDelta(rn, ['N'], pads, ['n'], (4.0, 3.0, 5.0, 0.0, 2.0))
    rn.set_net('n', anchors, [edge, ('A', '1', 0.0, 0.0, 'X', '1', 1.0, 1.0)])
    with pytest.raises(ValueError, match='endpoint'):
        native.NativeDelta(rn, ['N'], pads, ['n'], (4.0, 3.0, 5.0, 0.0, 2.0))


@pytest.mark.parametrize('rest_xy,new_xy', [
    ([], [(0, 0), (1, 0), (0, 1), (1, 1)]),
    ([(0, 0), (1, 0), (0, 1)], [(1, 1), (2, 0), (0, 2)]),
    ([(0, 0), (1, 0)], [(100, 100), (101, 100), (100, 101)]),
])
def test_native_certificate_keeps_equal_bound_edges_and_connects_new_only_nets(rest_xy, new_xy):
    from placemat import geometry
    from placemat.ratsnest import Ratsnest
    native = geometry._native
    if native is None or not hasattr(native, 'NativeDelta'):
        pytest.skip('NativeDelta not built')
    rn = Ratsnest(mirror=native.NativeRatsnest())
    rest = [Anchor('R%d' % i, '1', x, y) for i, (x, y) in enumerate(rest_xy)]
    rn.set_net('n', rest)
    new = [Anchor('N', str(i), x, y) for i, (x, y) in enumerate(new_xy)]
    delta = native.NativeDelta(rn.mirror, ['N'], [[('n', a.ref, a.number, a.x, a.y) for a in new]],
                              ['n'], (4.0, 3.0, 5.0, 0.0, 2.0))
    assert delta.wire_cross(0.0, 0.0, 0)[0] == pytest.approx(_length(mst('n', rest + new)) - _length(mst('n', rest)))


@pytest.mark.parametrize('fitted,push', [(False, False), (True, False), (False, True)])
def test_python_delta_matches_raw_live_whole_terms_without_mutation(fitted, push):
    from dataclasses import replace
    from placemat import score
    from placemat.board_geometry import members_of
    from placemat.score_delta import Delta
    from placemat.values import Location, Part
    from tests.test_score_measures import _push_board, _two_part_board
    if push:
        board = _push_board()
    else:
        board = _two_part_board()
        if fitted:
            board.rect(fit=True)
        board.place(Part('u1'), at=Location(10, 10))
        board.place(Part('c1'), at=Location(30, 30))
    plan = board.resolve()
    occ = plan.occupancy
    rng = random.Random(33)
    for step in plan.steps:
        if step.placement is None or step.item not in plan._items:
            continue
        item = plan._items[step.item]
        refs = [fp.ref for fp in members_of(item)]
        original = step.placement
        baseline = score.whole(board, occ, plan)
        occ.lift(refs)
        lifted = score.whole(board, occ, plan)
        delta = Delta(board, occ, item, plan.links, plan=plan)
        for _ in range(20):
            delta = Delta(board, occ, item, plan.links, plan=plan)
            candidate = replace(original, location=Location(original.location.x + rng.uniform(-0.1, 0.1),
                                                           original.location.y + rng.uniform(-0.1, 0.1)))
            change = delta(candidate, prune_above=-math.inf)
            assert score.whole(board, occ, plan) == lifted
            occ.commit(item, candidate)
            after = score.whole(board, occ, plan)
            for term, value in change.terms.items():
                assert value == pytest.approx(after[term] - lifted[term], abs=1e-6), (step.item, term)
            assert change.total == sum(change.terms.values())
            occ.lift(refs)
        occ.commit(item, original)
        restored = score.whole(board, occ, plan)
        assert restored == pytest.approx(baseline, abs=1e-6)


def test_delta_refuses_changed_or_outside_frames_instead_of_clipping_demand():
    from dataclasses import replace
    from placemat.score_delta import Delta
    from placemat.values import Box, Location
    from tests.test_score_measures import _push_board
    board = _push_board()
    plan = board.resolve()
    occ = plan.occupancy
    item = plan._items['u2']
    original = plan.placement('u2')
    occ.lift(['U2'])
    delta = Delta(board, occ, item, plan.links, plan=plan)
    with pytest.raises(ValueError, match='exceed'):
        delta(replace(original, location=Location(100, 100)))
    occ.board_box = Box(0, 0, 120, 120)
    with pytest.raises(ValueError, match='frame changed'):
        delta(original)
    with pytest.raises(ValueError, match='frame changed'):
        delta.native([original.rotation], original.face)


def test_cell_candidate_view_replaces_its_copper_and_matches_real_commit():
    from dataclasses import replace
    from placemat import score
    from placemat.layout import Board
    from placemat.score_delta import Delta
    from placemat.values import Box, Cell, Location
    from tests.test_cell_drops import _geom
    board = Board(_geom(), edge_margin=0.5)
    board.rect(fit=True)
    board.place(Cell('m'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['m']
    occ.board_box = Box(0, 0, 80, 80)  # the legal search room before final fit
    before_copper = list(occ.copper)
    occ.lift(['U1'])
    delta = Delta(board, occ, item, plan.links, plan=plan)
    original = plan.placement('m')
    candidate = replace(original, location=Location(25, 25))
    view, _, new = delta._view(candidate)
    assert new and [s for s in view.copper if s.owner == 'm'] == new
    assert occ.copper == before_copper
    expected = score.whole(board, view, plan)
    change = delta(candidate)
    lifted = score.whole(board, occ, plan)
    occ.commit(item, candidate)
    after = score.whole(board, occ, plan)
    assert after == pytest.approx(expected, abs=1e-6)
    for term, value in change.terms.items():
        assert value == pytest.approx(after[term] - lifted[term], abs=1e-6), term


@pytest.mark.parametrize('fitted', [False, True])
def test_native_layout_terms_match_python_delta_and_raw_whole(fitted):
    from dataclasses import replace
    from placemat import geometry, score
    from placemat.score_delta import Delta
    from placemat.values import LinkWeight, Location, PadRef, Part
    from tests.test_score_measures import _two_part_board
    if geometry._native is None or not hasattr(geometry._native.NativeDelta, 'configure_layout'):
        pytest.skip('NativeDelta layout not built')
    board = _two_part_board()
    if fitted:
        board.rect(fit=True)
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(30, 30))
    board.link(PadRef(Part('c1'), 1), PadRef(Part('u1'), 1), weight=LinkWeight.SHORT, limit_mm=15.0)
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    original = plan.placement('c1')
    occ.lift(['C1'])
    delta = Delta(board, occ, item, plan.links, plan=plan)
    turns = [0.0, 90.0, 33.0]
    native = delta.native(turns, original.face)
    assert native is not None
    keys = ('airwire', 'crossings', 'link', 'link_over', 'area', 'congestion')
    rng = random.Random(21)
    before = score.whole(board, occ, plan)
    for turn, rotation in enumerate(turns):
        for _ in range(30):
            delta = Delta(board, occ, item, plan.links, plan=plan)
            native = delta.native(turns, original.face)
            assert native is not None
            candidate = replace(original, rotation=rotation, location=Location(30+rng.uniform(-0.1, 0.1), 30+rng.uniform(-0.1, 0.1)))
            expected = delta(candidate)
            measured = dict(zip(keys, native.terms(candidate.location.x, candidate.location.y, turn)))
            assert measured == pytest.approx({k: expected.terms[k] for k in keys}, abs=1e-6)
            occ.commit(item, candidate)
            after = score.whole(board, occ, plan)
            assert measured == pytest.approx({k: after[k] - before[k] for k in keys}, abs=1e-6)
            occ.lift(['C1'])


def test_native_congestion_matches_one_ulp_step_boundaries_and_repeated_candidates():
    from placemat import geometry
    from placemat.congestion import RudyGrid
    from placemat.values import Box, Location
    native = geometry._native
    if native is None or not hasattr(native.NativeDelta, 'configure_layout'):
        pytest.skip('NativeDelta layout not built')
    boundary = 0.05 * (1 - 1e-9)
    pitches = [boundary]
    low = high = boundary
    for _ in range(4):
        low = math.nextafter(low, -math.inf)
        high = math.nextafter(high, math.inf)
        pitches.extend([low, high])
    levels = set()
    for pitch in pitches:
        grid = RudyGrid(Box(0, 0, 2, 2), 2, pitch, 0.05)
        point = Location(0.25, 0.25)
        grid.add_net('n', [point])
        expected = grid.change({'n': [point, point]})
        levels.add(expected)
        delta = native.NativeDelta(native.NativeRatsnest(), [], [[]], [], (4.0, 3.0, 5.0, 0.0, 2.0))
        delta.configure_layout([[]], [(0, 0, 0, 0)], None,
            ((0, 0, 2, 2), 2, pitch, 0.05, 0.5, 0.5, [('n', 0.25, 0.25)], [[('n', (0.25, 0.25, 0.25, 0.25))]]),
            (0.0, 0.0, 0.0, 1.0))
        for _ in range(20):
            assert delta.terms(0.0, 0.0, 0)[-1] == expected
    assert levels == {0, 1}


def test_native_multinet_scratch_cells_match_signed_rebuilds_without_drift():
    from placemat import geometry
    from placemat.congestion import RudyGrid
    from placemat.values import Box, Location
    native = geometry._native
    if native is None or not hasattr(native.NativeDelta, 'configure_layout'):
        pytest.skip('NativeDelta layout not built')
    rng = random.Random(19)
    rest = {str(n): [Location(rng.uniform(0.5, 9.5), rng.uniform(0.5, 9.5)) for _ in range(3)] for n in range(8)}
    grid = RudyGrid(Box(0, 0, 10, 10), 2, 0.4, 0.05)
    for net, points in rest.items():
        grid.add_net(net, points)
    pads = [(net, p.x, p.y) for net, points in rest.items() for p in points]
    moving = [('0', (0.0, 0.0, 0.0, 0.0)), ('1', (0.2, 0.1, 0.2, 0.1)), ('2', (-0.2, -0.1, -0.2, -0.1))]
    delta = native.NativeDelta(native.NativeRatsnest(), [], [[]], [], (4.0, 3.0, 5.0, 0.0, 2.0))
    delta.configure_layout([[]], [(0, 0, 0, 0)], None,
        ((0, 0, 10, 10), 2, 0.4, 0.05, 0.5, 0.5, pads, [moving]), (0.0, 0.0, 0.0, 1.0))
    changes = set()
    for _ in range(100):
        x, y = rng.uniform(1, 9), rng.uniform(1, 9)
        replacements = {net: rest[net] + [Location(geometry._clean(b[0] + x), geometry._clean(b[1] + y))]
                        for net, b in moving}
        expected = grid.change(replacements)
        changes.add(expected)
        assert delta.terms(x, y, 0)[-1] == expected
        assert delta.terms(x, y, 0)[-1] == expected
    assert min(changes) < 0  # spreading can lower the worst cell despite adding pads


def test_native_cell_layout_includes_carried_copper_in_fitted_bounds():
    from dataclasses import replace
    from placemat import geometry, score
    from placemat.layout import Board
    from placemat.score_delta import Delta
    from placemat.values import Box, Cell, Face, Location
    from tests.test_cell_drops import _geom
    if geometry._native is None or not hasattr(geometry._native.NativeDelta, 'configure_layout'):
        pytest.skip('NativeDelta layout not built')
    board = Board(_geom(), edge_margin=0.5)
    board.rect(fit=True)
    board.place(Cell('m'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['m']
    occ.board_box = Box(0, 0, 80, 80)
    occ.lift(['U1'])
    before = score.whole(board, occ, plan)
    delta = Delta(board, occ, item, plan.links, plan=plan)
    keys = ('airwire', 'crossings', 'link', 'link_over', 'area', 'congestion')
    for face in [Face.FRONT, Face.BACK]:
        for turn, rotation in enumerate([0, 37, 90, 143]):
            delta = Delta(board, occ, item, plan.links, plan=plan)
            kernel = delta.native([0, 37, 90, 143], face)
            assert kernel is not None
            candidate = replace(plan.placement('m'), face=face, rotation=rotation,
                                location=Location(25.0000000005, 25.0000000005))
            terms = dict(zip(keys, kernel.terms(candidate.location.x, candidate.location.y, turn)))
            expected = delta(candidate).terms
            anchors = occ.candidate_named_anchors(item, candidate)
            assert terms == pytest.approx({k: expected[k] for k in keys}, abs=1e-6), (face, rotation)
            assert terms['airwire'] == pytest.approx(expected['airwire'], rel=0, abs=1e-12)
            assert terms['crossings'] == expected['crossings']
            occ.commit(item, candidate)
            assert anchors == [(net, ref, pad, occ.pad_anchor(ref, pad).x, occ.pad_anchor(ref, pad).y)
                               for net, ref, pad, _, _ in anchors]
            after = score.whole(board, occ, plan)
            assert terms == pytest.approx({k: after[k] - before[k] for k in keys}, abs=1e-6)
            occ.lift(['U1'])


def test_native_grid_refuses_outside_and_overflowing_rest_snapshots():
    from placemat import geometry
    native = geometry._native
    if native is None or not hasattr(native.NativeDelta, 'configure_layout'):
        pytest.skip('NativeDelta layout not built')
    delta = native.NativeDelta(native.NativeRatsnest(), [], [[]], [], (4.0, 3.0, 5.0, 0.0, 2.0))
    with pytest.raises(ValueError, match='rest pads'):
        delta.configure_layout([[]], [(0, 0, 0, 0)], None,
            ((0, 0, 2, 2), 2, 0.4, 0.05, 0.5, 0.5, [('n', 1e300, 1e300)], [[]]), (0.0, 0.0, 0.0, 1.0))
    with pytest.raises(ValueError, match='grid|capacity'):
        delta.configure_layout([[]], [(0, 0, 0, 0)], None,
            ((-1e308, -1e308, 1e308, 1e308), 2, 0.4, 0.05, 0.5, 0.5,
             [('n', 1e300, 1e300)], [[]]), (0.0, 0.0, 0.0, 1.0))


def test_invalid_fixed_geometry_falls_back_with_its_validity_and_wire_evidence():
    from dataclasses import replace
    from placemat import score
    from placemat.score_delta import Delta
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    board = _two_part_board(keep_going=True)
    board.place(Part('u1'), at=Location(100, 100))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    measured = score.plan_measures(board, plan)
    assert not score.Validity.of(measured).valid
    assert measured['airwire_mm'] > 100
    occ = plan.occupancy
    occ.lift(['C1'])
    delta = Delta(board, occ, plan._items['c1'], plan.links, plan=plan)
    assert delta.scorable(plan.placement('c1'))
    outside = replace(plan.placement('c1'), location=Location(100, 100))
    assert not delta.scorable(outside)
    with pytest.raises(ValueError, match='candidate pads exceed the fixed search frame'):
        delta(outside)
    assert delta.native([0.0], plan.placement('c1').face) is None
    change = delta(plan.placement('c1'))
    assert change.terms['airwire'] > 100
    assert not score.Validity.of(measured).valid


def test_whole_cell_lift_owns_copper_but_partial_member_move_does_not():
    from placemat.escapes import search_near
    from placemat.occupancy import Occupancy
    from tests.fixtures import board_geometry, footprint
    from tests.test_cell_drops import _via
    geometry = board_geometry([
        footprint('U1', 10, 10, cell='m'), footprint('U2', 15, 10, cell='m'),
        footprint('U3', 30, 30, cell='other')], cells=['m', 'other'],
        copper=[_via('A', 12, 10, 'm'), _via('A', 30, 30, 'other')])
    occ = Occupancy(geometry)
    occ.escapes()  # Exercise refresh as well as the uncached obstacle reader.
    original = tuple(occ.copper)
    before = search_near(occ)
    obstacles = occ._obstacle_shapes(occ.pending)
    lifted = []
    for owners in [{'U1', 'U2'}, {'m'}, occ._geometry(geometry.cells['m']).owners]:
        occ.lift(owners)
        assert occ.pending == {'U1', 'U2', 'm'}
        assert all(s.owner not in occ.pending for s in search_near(occ))
        assert any(s.owner == 'other' for s in search_near(occ))
        lifted.append((search_near(occ), occ._obstacle_shapes(occ.pending), (dict(occ.escapes()._corr), dict(occ.escapes()._blockers))))
        occ.unlift(owners)
        assert not occ.pending
        assert tuple(occ.copper) == original
        assert search_near(occ) == before
        assert occ._obstacle_shapes(occ.pending) == obstacles
    assert lifted[0] == lifted[1] == lifted[2]
    occ.lift({'U1'})
    assert occ.pending == {'U1'}
    assert any(s.owner == 'm' for s in search_near(occ))
    assert any(s.owner == 'U2' for s in search_near(occ))
    occ.unlift({'U1'})
    assert search_near(occ) == before


@pytest.mark.slow
def test_repository_module_and_core_non_escape_delta_parity(monkeypatch):
    """Actual module/core raw objective and complete prepared escape parity."""
    from dataclasses import replace
    from time import perf_counter
    from fixtures import bench
    from fixtures.reference.lock import realboard
    from placemat import score
    from placemat.board_geometry import members_of
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.score_delta import Delta
    from placemat.values import Cell, Location, Part
    rng = random.Random(11)
    keys = ('airwire', 'crossings', 'link', 'link_over', 'push', 'area', 'congestion',
            'escape_crossed', 'escape_closed', 'escape_via')

    from placemat import geometry as geometry_kernel
    from placemat.prepared_escape import prepare
    from tests.test_prepared_escape import _assert_inspection
    native_module = geometry_kernel._native
    assert native_module is not None and hasattr(native_module, 'PreparedSurface'), 'designated full composition gate'

    def refusal(delta):
        if delta.has_push:
            return 'documented push/exposure intent fallback'
        if delta.lanes is not None:
            return 'documented caller-provided lanes fallback'
        if delta.rn.mirror is None:
            pytest.fail('designated native gate lacks ratsnest mirror')
        if delta.grid is not None:
            frame = delta.grid.board
            if any(not frame.contains_point(point) for pads in delta.occ.__dict__['_congestion_pads'].values()
                   for point in pads.values()):
                return 'documented invalid fixed-frame geometry fallback'
        pytest.fail('unexplained native refusal in designated complete composition gate')

    total_coverage = {}

    def check(board, plan, limit, label):
        from collections import Counter
        from placemat.board_geometry import Footprint
        coverage = {}
        occ = plan.occupancy
        selected = [s for s in plan.steps if s.placement is not None and s.item in plan._items][:limit]
        for step in selected:
            item = plan._items[step.item]
            owners = [fp.ref for fp in members_of(item)]
            original = score.whole(board, occ, plan)
            occ.lift(owners)
            before = score.whole(board, occ, plan)
            delta = Delta(board, occ, item, plan.links, plan=plan)
            kernel = delta.native([step.placement.rotation], step.placement.face)
            candidates = [step.placement]
            for _ in range(4):
                candidate = replace(step.placement, location=Location(
                    step.placement.location.x + rng.uniform(-0.1, 0.1),
                    step.placement.location.y + rng.uniform(-0.1, 0.1)))
                if occ.legal(item, candidate, board.geometry.default_clearance) is None:
                    candidates.append(candidate)
            for candidate in candidates:
                delta = Delta(board, occ, item, plan.links, plan=plan)
                kernel = delta.native([step.placement.rotation], step.placement.face)
                change = delta(candidate)
                view, geometries, copper = delta._view(candidate)
                from placemat.escapes import judging, _layer_bits
                prepared = delta.native_shapes([candidate.rotation], candidate.face)
                assert prepared is not None
                _, moved = occ.candidate_shapes(item, candidate)
                expected_shapes = [(s.owner, s.kind, s.net, s.label, _layer_bits(s.layers), list(s.poly),
                                    (s.box.left, s.box.top, s.box.right, s.box.bottom), list(s.ends), bool(s.lane), s.wire)
                                   for s in moved]
                assert prepared.shapes(candidate.location.x, candidate.location.y, 0) == expected_shapes
                oracle_counts = {key: len(value) for key, value in judging(view).found().items()}
                for classifier in (False, True):
                    counts, _ = delta._escape_delta.change(view, geometries, copper, native=classifier)
                    assert counts == oracle_counts, (step.item, candidate, classifier)
                assert change.walled == oracle_counts.get('escape_walled', 0)
                assert change.walled_change == change.walled - delta._escape_base.get('escape_walled', 0)
                kind = 'part' if isinstance(item, Footprint) else 'cell'
                row = coverage.setdefault(kind, {'native': 0, 'fallback': Counter(), 'cache_reused': 0, 'cache_rejudged': 0})
                total = total_coverage.setdefault(kind, {'native': 0, 'fallback': Counter(), 'cache_reused': 0, 'cache_rejudged': 0})
                if kernel is None:
                    why = refusal(delta)
                    row['fallback'][why] += 1
                    total['fallback'][why] += 1
                else:
                    row['native'] += 1
                    total['native'] += 1
                if kernel is not None:
                    full, reason = prepare(delta, [candidate.rotation], candidate.face)
                    assert full is not None, (step.item, reason)
                    full_terms, full_crossed, full_vias, full_away, full_walled, ways, walls = full.evaluate(candidate, 0, inspect=True)
                    cached, reason = prepare(delta, [candidate.rotation], candidate.face, rest_cache=True)
                    assert cached is not None, (step.item, reason)
                    assert cached.evaluate(candidate, 0, inspect=True) == (
                        full_terms, full_crossed, full_vias, full_away, full_walled, ways, walls)
                    reused, rejudged = cached.surface.cache_usage()
                    for measured in (row, total):
                        measured['cache_reused'] += reused
                        measured['cache_rejudged'] += rejudged
                    # The independent oracle rebuilds its own ratsnest and
                    # classifies geometry in Python; the native snapshot is
                    # immutable and cannot provide cached answers to it.
                    python_view, _, _ = delta._view(candidate)
                    with monkeypatch.context() as pure:
                        pure.setattr(geometry_kernel, '_native', None)
                        oracle = judging(python_view)
                        full_counts = oracle.counts()
                        _assert_inspection(oracle, ways, walls)
                    assert (full_crossed, full_vias, full_away, full_walled) == (
                        full_counts['escape_crossed'] - delta._escape_base['escape_crossed'],
                        full_counts['escape_via'], full_counts['escape_closed'], full_counts['escape_walled']), (step.item,candidate)
                    assert full_terms == pytest.approx(tuple(change.terms[k] for k in
                        ('airwire','crossings','link','link_over','area','congestion')), abs=1e-6)
                    assert full_terms[1] == change.terms['crossings']
                native = kernel.terms(candidate.location.x, candidate.location.y, 0) if kernel else None
                if kernel is not None:
                    assert kernel.escape_cross(candidate.location.x, candidate.location.y, 0,
                                               board.settings.score_escape_depth) == (
                        oracle_counts.get('escape_crossed', 0) - delta._escape_base.get('escape_crossed', 0))
                occ.commit(item, candidate)
                after = score.whole(board, occ, plan)
                expected = {k: after[k] - before[k] for k in keys}
                assert {k: change.terms[k] for k in keys} == pytest.approx(expected, abs=1e-6), (step.item, candidate)
                if native is not None:
                    assert dict(zip(('airwire', 'crossings', 'link', 'link_over', 'area', 'congestion'), native)) == pytest.approx(
                        {k: expected[k] for k in ('airwire', 'crossings', 'link', 'link_over', 'area', 'congestion')}, abs=1e-6)
                occ.lift(owners)
            occ.commit(item, step.placement)
            assert score.whole(board, occ, plan) == pytest.approx(original, abs=1e-6)

        assert coverage, (label, 'no candidates exercised')
        for kind, row in coverage.items():
            # Zero supported rows are only admitted with an individually
            # proved, documented exclusion from the current native contract.
            assert row['native'] > 0 or row['fallback'], (label, kind, row)
        print('FULL_PREPARED_COVERAGE', label, coverage, flush=True)

    with realboard():
        for path in bench.boards()[:6]:
            label, started = bench._name(path), perf_counter()
            print('FULL_PREPARED_START', label, flush=True)
            geometry = read_board(path)
            board = bench.ModuleBoard(geometry, {}, bench._planes(geometry), bench._size(geometry, False))()
            plan = board.resolve()
            print('FULL_PREPARED_RESOLVED', label, perf_counter() - started, flush=True)
            check(board, plan, 8, label)
            print('FULL_PREPARED_SECONDS', label, perf_counter() - started, flush=True)
        started = perf_counter()
        print('FULL_PREPARED_START', 'written-core', flush=True)
        geometry = read_board(bench.BOARD_FIXTURE / 'layout' / 'layout.kicad_pcb')
        board = Board(geometry, keep_going=True)
        board.outline(geometry.board_polygon[0], holes=geometry.board_polygon[1:])
        # The written core supplies a real placed board; no unrelated search is needed.
        for name, cell in sorted(geometry.cells.items()):
            if cell.members:
                from placemat.occupancy import Occupancy
                reference = Occupancy(geometry)._geometry(cell).reference
                board.place(Cell(name), at=reference.location, rotation=reference.rotation, face=reference.face)
        for fp in geometry.footprints:
            if fp.cell is None:
                board.place(Part(fp.inst), at=fp.location, rotation=fp.rotation, face=fp.face)
        check(board, board.resolve(), 8, 'written-core')
        print('FULL_PREPARED_SECONDS', 'written-core', perf_counter() - started, flush=True)
    assert total_coverage['part']['native'] > 0, total_coverage
    assert total_coverage['part']['cache_reused'] > 0, total_coverage
    assert total_coverage['part']['cache_rejudged'] > 0, total_coverage
    assert total_coverage.get('cell', {}).get('native', 0) > 0 or (
        total_coverage.get('cell', {}).get('fallback')
        and set(total_coverage['cell']['fallback']) <= {'documented push/exposure intent fallback',
                                                    'documented invalid fixed-frame geometry fallback'}), total_coverage
    print('FULL_PREPARED_TOTAL', total_coverage, flush=True)


def test_native_configuration_failure_is_not_cached(monkeypatch):
    from placemat import geometry
    from placemat.score_delta import Delta
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    occ = plan.occupancy
    occ.lift(['C1'])
    delta = Delta(board, occ, plan._items['c1'], plan.links, plan=plan)
    attempts = []
    class Refused:
        def __init__(self, *args):
            pass
        def configure_affines(self, *args):
            pass
        def configure_layout(self, *args):
            attempts.append(1)
            raise ValueError('invalid grid snapshot')
    if geometry._native is None:
        pytest.skip('native module unavailable')
    monkeypatch.setattr(geometry._native, 'NativeDelta', Refused)
    for _ in range(2):
        with pytest.raises(ValueError, match='invalid grid snapshot'):
            delta.native([0.0], plan.placement('c1').face)
        assert delta._native == {}
    assert len(attempts) == 2


def test_lift_owner_closure_is_independent_of_cell_mapping_order():
    from dataclasses import replace
    from placemat.occupancy import Occupancy
    from tests.fixtures import board_geometry, footprint
    geometry = board_geometry([footprint('U1', 10, 10, cell='a'),
                               footprint('U2', 20, 20, cell='b')], cells=['a', 'b'])
    a, b = geometry.cells['a'], geometry.cells['b']
    both = replace(a, name='both', members=a.members + b.members)
    for cells in [dict(both=both, a=a, b=b), dict(b=b, a=a, both=both)]:
        occ = Occupancy(replace(geometry, cells=cells))
        assert occ._lift_owners({'both'}) == {'both', 'a', 'b', 'U1', 'U2'}
        assert occ._lift_owners({'U1', 'U2'}) == {'both', 'a', 'b', 'U1', 'U2'}


def test_candidate_anchors_match_committed_affine_at_half_nanometre_translations():
    from placemat import geometry
    from placemat.score_delta import Delta
    from placemat.values import Face, Location, Part
    from placemat.placement import Placement
    from tests.test_score_measures import _two_part_board
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    original = plan.placement('c1')
    for face in (Face.FRONT, Face.BACK, Face.FRONT):
        for rotation in (0, 37, 90, 143):
            for offset in (-0.0000000005, 0.0000000005):
                candidate = Placement(Location(20 + offset, 20 - offset), rotation, face)
                occ.lift(['C1'])
                actual = occ.candidate_named_anchors(item, candidate)
                delta = Delta(board, occ, item, plan.links, plan=plan)
                kernel = delta.native([rotation], face)
                if hasattr(getattr(geometry._native, 'NativeDelta', None), 'configure_affines'):
                    assert kernel is not None
                change = delta(candidate)
                if kernel is not None:
                    wire, crossings = kernel.wire_cross(candidate.location.x, candidate.location.y, 0)
                    assert wire == pytest.approx(change.terms['airwire'], abs=1e-12, rel=0)
                    assert crossings == change.terms['crossings']
                occ.commit(item, candidate)
                expected = [(net, ref, pad, occ.pad_anchor(ref, pad).x, occ.pad_anchor(ref, pad).y)
                            for net, ref, pad, _, _ in actual]
                assert actual == expected, (candidate, actual, expected)
                occ.commit(item, original)


def test_native_anchor_affine_configuration_refuses_malformed_records_atomically():
    from placemat.score_delta import Delta
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    original = plan.placement('c1')
    occ.lift(['C1'])
    delta = Delta(board, occ, item, plan.links, plan=plan)
    kernel = delta.native([original.rotation], original.face)
    if kernel is None:
        pytest.skip('exact native affine kernel unavailable')
    records = occ.candidate_anchor_affines(item, original)
    baseline = kernel.wire_cross(20, 20, 0)
    invalid = [[], [[*records, records[0]]], [[(records[0][0], records[0][1], records[0][2], [0.0])]]]
    for value in invalid:
        with pytest.raises(ValueError):
            kernel.configure_affines(value)
        assert kernel.wire_cross(20, 20, 0) == baseline
    for bad in (float('inf'), float('nan'), 1e20):
        values = list(records[0][3])
        values[9] = bad
        row = records[0][:3] + (values,)
        with pytest.raises(ValueError):
            kernel.configure_affines([[row] + records[1:]])
        assert kernel.wire_cross(20, 20, 0) == baseline


@pytest.mark.parametrize('changed', ['moving', 'rest', 'lift'])
def test_delta_refuses_mutated_occupancy_and_fresh_snapshot_rebuilds(changed):
    from placemat.score_delta import Delta
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    original = plan.placement('c1')
    occ.lift(['C1'])
    delta = Delta(board, occ, item, plan.links, plan=plan)
    first = delta(original)
    assert delta(original) == first
    if changed == 'moving':
        occ.commit(item, original)
        occ.lift(['C1'])
    elif changed == 'rest':
        occ.commit(plan._items['u1'], plan.placement('u1'))
    else:
        occ.unlift(['C1'])
        occ.lift(['C1'])
    with pytest.raises(ValueError, match='occupancy changed'):
        delta(original)
    with pytest.raises(ValueError, match='occupancy changed'):
        delta.native([original.rotation], original.face)
    view, geometries, copper = delta._view(original)
    with pytest.raises(ValueError, match='occupancy changed'):
        delta._escape_delta.change(view, geometries, copper)
    fresh = Delta(board, occ, item, plan.links, plan=plan)
    assert fresh(original) == first


def test_delta_refuses_direct_pending_change_and_frame_change_without_congestion():
    from dataclasses import replace
    from placemat.score_delta import Delta
    from placemat.values import Box, Location, Part
    from tests.test_score_measures import _two_part_board
    board = _two_part_board()
    board.settings = replace(board.settings, score_congestion_step=0)
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    original = plan.placement('c1')
    occ.lift(['C1'])
    delta = Delta(board, occ, item, plan.links, plan=plan)
    occ.pending.add('U1')
    with pytest.raises(ValueError, match='pending geometry'):
        delta(original)
    with pytest.raises(ValueError, match='pending geometry'):
        delta.native([original.rotation], original.face)
    occ.pending.remove('U1')
    occ.board_box = Box(0, 0, 80, 80)
    with pytest.raises(ValueError, match='frame changed'):
        delta(original)
    with pytest.raises(ValueError, match='frame changed'):
        delta.native([original.rotation], original.face)


@pytest.mark.parametrize('kind', ['part', 'cell'])
def test_native_prepared_candidate_polygons_match_full_affine_and_layer_flip_exactly(kind):
    from placemat import geometry
    from placemat.escapes import _layer_bits
    from placemat.layout import Board
    from placemat.placement import Placement
    from placemat.score_delta import Delta
    from placemat.values import Cell, Face, Location, Part
    from tests.test_cell_drops import _geom
    from tests.test_score_measures import _two_part_board
    if not hasattr(geometry._native, 'PreparedCandidate'):
        pytest.skip('prepared native candidate geometry not built')
    if kind == 'cell':
        board = Board(_geom(), edge_margin=0.5)
        board.rect(fit=True)
        board.place(Cell('m'), at=Location(20, 20))
        key, refs = 'm', ['U1']
    else:
        board = _two_part_board()
        board.place(Part('u1'), at=Location(10, 10))
        board.place(Part('c1'), at=Location(20, 20))
        key, refs = 'c1', ['C1']
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items[key]
    occ.lift(refs)
    delta = Delta(board, occ, item, plan.links, plan=plan)
    turns = [0, 37, 90, 143]
    for face in (Face.FRONT, Face.BACK, Face.FRONT):
        native = delta.native_shapes(turns, face)
        assert native is not None
        for index, rotation in enumerate(turns):
            for offset in (-0.0000000005, 0.0000000005, 0.0):
                placement = Placement(Location(20 + offset, 20 - offset), rotation, face)
                _, expected = occ.candidate_shapes(item, placement)
                records = [(s.owner, s.kind, s.net, s.label, _layer_bits(s.layers), list(s.poly),
                            (s.box.left, s.box.top, s.box.right, s.box.bottom), list(s.ends), bool(s.lane), s.wire)
                           for s in expected]
                assert native.shapes(placement.location.x, placement.location.y, index) == records
                assert native.shapes(placement.location.x, placement.location.y, index) == records
    occ.commit(item, plan.placement(key))
    occ.lift(refs)
    with pytest.raises(ValueError, match='occupancy changed'):
        delta.native_shapes(turns, Face.FRONT)


def test_native_prepared_aim_uses_raw_squared_distance_before_stable_pad_ties():
    from placemat import geometry
    from placemat.ratsnest import Ratsnest
    module = geometry._native
    if module is None or not hasattr(getattr(module, 'NativeDelta', None), 'aim'):
        pytest.skip('native prepared aim not built')
    rn = Ratsnest(mirror=module.NativeRatsnest())
    # These target lengths quantize to the same nm MST weight, but B0 is
    # strictly farther in the escape oracle's raw squared-distance comparison.
    rest = [Anchor('P0', '1', 0, 0), Anchor('B0', '1', 2, 0.000001), Anchor('Y0', '1', 2, 0)]
    rn.set_net('S', rest)
    rn.set_net('untouched', [Anchor('Q1', '1', -2, 0), Anchor('Q0', '1', 2, 0)])
    # On glibc this square differs from multiplication by one ulp. A0 and
    # Z9 tie under x*x, while the CPython pow oracle prefers Z9. Calculate
    # the expected answer with Python so the test retains the platform's
    # own C-pow semantics on other wheel targets too.
    pow_targets = [Anchor('A0', '1', 0.1, 910.4575114352892),
                   Anchor('Z9', '1', -910.4575169270337, 0)]
    rn.set_net('pow', pow_targets)
    kernel = module.NativeDelta(rn.mirror, ['Z0'], [[('S', 'Z0', '1', 3, 0)]],
                                ['S', 'untouched', 'pow'], (4, 3, 5, 0, 2))
    assert kernel.aim(0, 0, 0, 'S', 'P0', '1', (0, 0)) == (2, 0)
    assert kernel.aim(-5, 0, 0, 'S', 'P0', '1', (0, 0)) == (2, 0)
    assert kernel.aim(-3.5, 0, 0, 'S', 'P0', '1', (0, 0)) == (-0.5, 0)
    assert kernel.aim(0, 0, 0, 'untouched', 'absent', '1', (0, 0)) == (2, 0)
    expected = min(pow_targets, key=lambda a: a.x ** 2 + a.y ** 2)
    assert kernel.aim(0, 0, 0, 'pow', 'absent', '1', (0, 0)) == (expected.x, expected.y)
    assert kernel.aim(0, 0, 0, 'absent', 'P0', '1', (0, 0)) is None
    for centre in [(float('nan'), 0), (float('inf'), 0), (1e20, 0)]:
        with pytest.raises(ValueError, match='aim'):
            kernel.aim(0, 0, 0, 'S', 'P0', '1', centre)


def test_native_prepared_aim_matches_python_pow_distance_on_repeated_candidates():
    from placemat import geometry
    from placemat.ratsnest import Ratsnest
    module = geometry._native
    if module is None or not hasattr(getattr(module, 'NativeDelta', None), 'aim'):
        pytest.skip('native prepared aim not built')
    rng = random.Random(79)
    rest = [Anchor(str(i), '1', rng.uniform(-1000, 1000), rng.uniform(-1000, 1000)) for i in range(20)]
    rn = Ratsnest(mirror=module.NativeRatsnest())
    rn.set_net('S', list(reversed(rest)))  # snapshot insertion order must not define ties
    kernel = module.NativeDelta(rn.mirror, ['N'], [[('S', 'N', '1', 0, 0)]], ['S'], (4, 3, 5, 0, 2))
    for _ in range(200):
        x, y = rng.uniform(-1000, 1000), rng.uniform(-1000, 1000)
        centre = (rng.uniform(-1000, 1000), rng.uniform(-1000, 1000))
        nodes = sorted(rest + [Anchor('N', '1', x, y)], key=lambda a: (a.ref, a.number))
        expected = min(nodes, key=lambda a: (a.x - centre[0]) ** 2 + (a.y - centre[1]) ** 2)
        assert kernel.aim(x, y, 0, 'S', 'unplaced', '1', centre) == (expected.x - centre[0], expected.y - centre[1])


def test_native_delta_refuses_unlifted_owner_even_on_net_without_added_anchors():
    from placemat import geometry
    from placemat.ratsnest import Ratsnest
    module = geometry._native
    if module is None or not hasattr(module, 'NativeDelta'):
        pytest.skip('native delta not built')
    rn = Ratsnest(mirror=module.NativeRatsnest())
    rn.set_net('unmodified', [Anchor('N', '2', 1, 1), Anchor('R', '1', 2, 2)])
    with pytest.raises(ValueError, match='lifted'):
        module.NativeDelta(rn.mirror, ['N'], [[('modified', 'N', '1', 0, 0)]],
                           ['modified', 'unmodified'], (4, 3, 5, 0, 2))


def test_native_prepared_candidate_refuses_malformed_geometry_and_recovers_after_bad_candidate():
    from placemat import geometry
    if not hasattr(geometry._native, 'PreparedCandidate'):
        pytest.skip('prepared native candidate geometry not built')
    native = geometry._native.PreparedCandidate
    shape = ('U1', 'pad', 'S', '1', 1, [(0, 0), (1, 0), (1, 1), (0, 1)], [(0.5, 0.5)], False, False)
    identity = (1, 0, 0, 1, 0, 0)
    for source in ([], [((float('nan'), 0, 0, 1, 0, 0), [shape])],
                   [(identity, [shape[:5] + ([],) + shape[6:]])],
                   [(identity, [shape[:5] + ([(float('inf'), 0)],) + shape[6:]])]):
        with pytest.raises(ValueError):
            native(source)
    snapshot = native([(identity, [shape])])
    baseline = snapshot.shapes(0, 0, 0)
    for x, y, turn in ((float('nan'), 0, 0), (0, 0, 1), (1e9, 0, 0)):
        with pytest.raises(ValueError):
            snapshot.shapes(x, y, turn)
        assert snapshot.shapes(0, 0, 0) == baseline


def test_lazy_escape_oracle_refuses_changed_occupancy_before_setup(monkeypatch):
    from placemat.score_delta import Delta
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    board = _two_part_board()
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(20, 20))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    occ.lift({'C1'})
    delta = Delta(board, occ, item, plan.links, plan=plan)
    assert delta._escape_snapshot is None
    def forbidden(*args):
        pytest.fail('stale lazy oracle must refuse before geometry setup')
    monkeypatch.setattr('placemat.escapes.EscapeDelta', forbidden)
    occ.unlift({'C1'})
    with pytest.raises(ValueError, match='snapshot|occupancy|lifted'):
        _ = delta._escape_base


@pytest.mark.parametrize('moving_ref', ['U9', 'R9'])
def test_netless_pad_obstacles_keep_escape_delta_native_and_whole_parity(moving_ref, monkeypatch):
    from dataclasses import replace
    from placemat import geometry, score
    from placemat.prepared_escape import prepare
    from placemat.score_delta import Delta
    from placemat.values import Location
    from tests.test_escape_findings import _walled_in
    from tests.test_surface_escapes import _via_only_board
    parts = _walled_in(0.1)
    parts[1] = replace(parts[1], pads=tuple(replace(pad, net='') for pad in parts[1].pads))
    board = _via_only_board(parts)
    # Real readers omit the unnamed net from the declared net table.
    board.geometry = replace(board.geometry, nets=board.geometry.nets - {''},
                             netclasses={n: c for n, c in board.geometry.netclasses.items() if n})
    plan = board.resolve()
    occ = plan.occupancy
    item = next(part for part in parts if part.ref == moving_ref)
    original = plan.placement(item.inst)
    occ.lift({moving_ref})
    before = score.whole(board, occ, plan)
    walls = []
    for pose in (original, replace(original, location=Location(30, 15))):
        delta = Delta(board, occ, item, plan.links, plan=plan)
        with monkeypatch.context() as context:
            context.setattr(geometry, "_native", None)
            expected = delta(pose)
        prepared, reason = prepare(delta, (0.0,), pose.face, rest_cache=True)
        assert prepared is not None, reason
        actual = prepared.evaluate(pose, 0, inspect=True)
        # Same-body prepared inspection exposes complete categorical counts.
        terms, crossed, vias, away, native_wall, _, _ = actual
        keys = ('airwire', 'crossings', 'link', 'link_over', 'area', 'congestion')
        assert terms == pytest.approx(tuple(expected.terms[k] for k in keys), abs=1e-6)
        view, _, _ = delta._view(pose)
        from placemat.escapes import judging
        with monkeypatch.context() as context:
            context.setattr(geometry, "_native", None)
            counts = judging(view).counts()
        assert (crossed, vias, away, native_wall) == (
            counts['escape_crossed'] - delta._escape_base['escape_crossed'],
            counts['escape_via'], counts['escape_closed'], counts['escape_walled'])
        occ.commit(item, pose)
        with monkeypatch.context() as context:
            context.setattr(geometry, "_native", None)
            whole = score.whole(board, occ, plan)
        final = score._incremental(board, occ, plan)['findings'].get('escape_walled', 0)
        for term, change in expected.terms.items():
            assert change == pytest.approx(whole[term] - before[term]), term
        assert expected.walled == final
        walls.append(final)
        # Whole geometry still contains the netless pad blockers.
        assert any(sh.net == '' for sh in occ.items['R9'].shapes)
        occ.lift({moving_ref})
    assert walls[0] > walls[1]


def test_escape_delta_does_not_treat_unknown_nonempty_net_as_netless():
    from dataclasses import replace
    from placemat.escapes import EscapeDelta
    from tests.test_escape_findings import _walled_in
    from tests.test_surface_escapes import _via_only_board
    board = _via_only_board(_walled_in(0.1))
    plan = board.resolve()
    occ = plan.occupancy
    occ.lift({'U9'})
    occ.geometry = replace(occ.geometry, nets=occ.geometry.nets - {'RING'},
                           netclasses={n: c for n, c in occ.geometry.netclasses.items() if n!='RING'})
    with pytest.raises(KeyError, match="no net named 'RING'"):
        EscapeDelta(occ, {'U9'})


def test_native_terms_match_python_and_whole_for_a_short_net_crossing_the_box_floor():
    """A net whose box is under `score.congestion_box` at some candidates and over it at others: the native search,
    the Python delta and the whole board agree on every term."""
    from dataclasses import replace
    from placemat import geometry, score
    from placemat.score_delta import Delta
    from placemat.settings import Settings
    from placemat.values import Location, Part
    from tests.test_score_measures import _two_part_board
    if geometry._native is None or not hasattr(geometry._native.NativeDelta, 'configure_layout'):
        pytest.skip('NativeDelta layout not built')
    floor = 3.0
    board = _two_part_board(settings=Settings(score_congestion_box=floor))
    board.place(Part('u1'), at=Location(10, 10))
    board.place(Part('c1'), at=Location(16, 10))
    plan = board.resolve()
    occ, item = plan.occupancy, plan._items['c1']
    original = plan.placement('c1')
    occ.lift(['C1'])
    turns = [0.0, 90.0, 180.0]
    keys = ('airwire', 'crossings', 'link', 'link_over', 'area', 'congestion')
    rng = random.Random(5)
    before = score.whole(board, occ, plan)
    spans, moved = set(), set()
    for turn, rotation in enumerate(turns):
        for _ in range(20):
            delta = Delta(board, occ, item, plan.links, plan=plan)
            native = delta.native(turns, original.face)
            assert native is not None
            candidate = replace(original, rotation=rotation,
                                location=Location(16 + rng.uniform(-1.0, 1.0), 10 + rng.uniform(-1.0, 1.0)))
            expected = delta(candidate)
            measured = dict(zip(keys, native.terms(candidate.location.x, candidate.location.y, turn)))
            assert measured == pytest.approx({k: expected.terms[k] for k in keys}, abs=1e-6)
            occ.commit(item, candidate)
            gnd = [occ.pad_location(ref, pad) for ref, pad in (('U1', '2'), ('C1', '2'))]
            spans.add(abs(gnd[0].x - gnd[1].x) < floor)
            after = score.whole(board, occ, plan)
            assert measured == pytest.approx({k: after[k] - before[k] for k in keys}, abs=1e-6)
            moved.add(measured['congestion'])
            occ.lift(['C1'])
    assert spans == {True, False}
    assert len(moved) > 1
