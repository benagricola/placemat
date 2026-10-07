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
    for _ in range(500):
        x, y = rng.uniform(0, 20), rng.uniform(0, 20)
        nodes = {net: list(anchors) for net, anchors in rest.items()}
        for net, ref, number, px, py in origins:
            nodes[net].append(Anchor(ref, number, px + x, py + y))
        after = measured(nodes)
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
