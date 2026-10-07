"""Prepared copper contact decisions retain the strict placement predicates."""
import pytest

from placemat import geometry
from tests.conftest import needs_native

pytestmark = needs_native


def _shape(owner, kind, net, number, bounds, *, layers=1, lane=False, wire=False):
    x0, y0, x1, y1 = bounds
    return (owner, kind, net, number, layers,
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], bounds, [], lane, wire)


def _candidate(module, shape):
    record = shape[:6] + shape[7:]
    return module.PreparedCandidate([((1, 0, 0, 1, 0, 0), [record])])


def test_prepared_contacts_follow_same_net_chain_and_original_pad_layers():
    module = geometry._native
    assert module is not None and hasattr(module, 'PreparedContacts')
    main = _shape('U1', 'pad', 'S', '1', (0, 0, 1, 1))
    rest = [
        _shape('drawn', 'copper', 'S', '', (0.5, 0, 2, 1), lane=True),
        _shape('drawn', 'copper', 'S', '', (1.5, 0, 3, 1), wire=True),
        _shape('U2', 'pad', 'S', '1', (2.5, 0, 3.5, 1)),
        # A through shape on another pad layer cannot enter this chain even
        # when it touches a multilayer piece further along the chain.
        _shape('drawn', 'through', 'S', '', (1.5, 0, 2.5, 1), layers=2),
        _shape('drawn', 'copper', 'OTHER', '', (0, 0, 3, 1)),
    ]
    snapshot = module.PreparedContacts(rest, ['U1', 'U2'])
    candidate = _candidate(module, main)
    got = snapshot.contacts(candidate, 0, 0, 0, 'U1', '1', 'S')
    assert got[:2] == (True, False)
    assert set(got[2]) == {0, 1}
    assert got[3:] == (True, False, True)
    assert snapshot.contacts(candidate, 0, 0, 0, 'U1', '1', 'S') == got
    # Edge-only contact is not a placement join; translation removes the
    # chain and cannot leave cached contact evidence from the prior candidate.
    assert snapshot.contacts(candidate, -0.5, 0, 0, 'U1', '1', 'S') == (
        False, False, [], False, False, True)
    assert snapshot.contacts(candidate, 0, 0, 0, 'U1', '1', 'S') == got


@pytest.mark.parametrize('layers,net,joined', [(1, 'S', True), (2, 'S', False), (1, 'OTHER', False)])
def test_prepared_contacts_distinguish_other_pad_from_drawn_copper(layers, net, joined):
    module = geometry._native
    assert module is not None and hasattr(module, 'PreparedContacts')
    main = _shape('U1', 'pad', 'S', '1', (0, 0, 1, 1))
    other = _shape('U2', 'through', net, '1', (0.5, 0, 1.5, 1), layers=layers)
    snapshot = module.PreparedContacts([other], ['U1', 'U2'])
    assert snapshot.contacts(_candidate(module, main), 0, 0, 0, 'U1', '1', 'S') == (
        False, joined, [], False, False, True)


def test_prepared_contacts_refuse_bad_bounds_missing_pad_and_weakened_net():
    module = geometry._native
    assert module is not None and hasattr(module, 'PreparedContacts')
    shape = _shape('U1', 'pad', 'S', '1', (0, 0, 1, 1))
    for invalid in (shape[:6] + ((0, 0, 0.5, 0.5),) + shape[7:],
                    shape[:7] + ([(float('nan'), 0)],) + shape[8:],
                    shape[:7] + ([(2, 2)],) + shape[8:],
                    _shape('U1', 'pad', 'S', '1', (0, 0, 1, 1), layers=0),
                    _shape('U1', 'unknown', 'S', '1', (0, 0, 1, 1))):
        with pytest.raises(ValueError):
            module.PreparedContacts([invalid], ['U1'])
    snapshot = module.PreparedContacts([], ['U1'])
    candidate = _candidate(module, shape)
    for number, net in [('absent', 'S'), ('1', 'OTHER')]:
        with pytest.raises(ValueError):
            snapshot.contacts(candidate, 0, 0, 0, 'U1', number, net)
    for invalid in [_shape('U1', 'unsupported', 'S', '1', (0, 0, 1, 1)),
                    _shape('U1', 'pad', 'S', '1', (0, 0, 1, 1), layers=0)]:
        with pytest.raises(ValueError):
            snapshot.contacts(_candidate(module, invalid), 0, 0, 0, 'U1', '1', 'S')
    # Known non-contact shapes are deliberately ignored; malformed wall
    # geometry is refused even when this pad's contact facts would be empty.
    bad_wall = ('rule', 'viaban', '', '', 0, [(0, 0), (1, 1), (2, 2)], [], False, False)
    source = shape[:6] + shape[7:]
    invalid = module.PreparedCandidate([((1, 0, 0, 1, 0, 0), [source, bad_wall])])
    with pytest.raises(ValueError):
        snapshot.contacts(invalid, 0, 0, 0, 'U1', '1', 'S')
    assert snapshot.contacts(candidate, 0, 0, 0, 'U1', '1', 'S') == (
        False, False, [], False, False, True)
    # Analytic pad extents may conservatively contain their polygon. This is
    # admitted unchanged; exact polygon overlap still determines contact.
    broad = shape[:6] + ((-1, -1, 2, 2),) + shape[7:]
    assert module.PreparedContacts([broad], ['U1']).contacts(
        candidate, 2, 0, 0, 'U1', '1', 'S')[:2] == (False, False)


def test_prepared_contacts_match_python_drawn_chain_and_pad_contact_after_moves(monkeypatch):
    from dataclasses import replace
    from placemat.escapes import judging, _layer_bits
    from placemat.score_delta import Delta
    from placemat.values import Location
    from tests.fixtures import board_geometry, pad, track
    from tests.test_final_board import _placed
    from tests.test_surface_escapes import _part_of
    module = geometry._native
    assert module is not None and hasattr(module, 'PreparedContacts')
    parts = [_part_of('U1', 'u1', [pad('U1', 'u1', 1, 'S', 10, 10, 1, 1)], 10, 10),
             _part_of('U2', 'u2', [pad('U2', 'u2', 1, 'S', 15, 10, 1, 1)], 15, 10)]
    board, plan = _placed(board_geometry(parts, copper=[track('S', 10, 10, 13, 10, w=0.4),
                                                       track('S', 13, 10, 15, 10, w=0.4)]))
    occ, item = plan.occupancy, parts[0]
    original = plan.placement('u1')
    occ.lift({'U1'})
    delta = Delta(board, occ, item, plan.links, plan=plan)
    candidate = delta.native_shapes([0], original.face)
    assert candidate is not None
    esc = judging(occ)
    rest = [s for pool in esc._blockers.values() for s in pool]
    records = [(s.owner, s.kind, s.net, s.label, _layer_bits(s.layers), list(s.poly),
                (s.box.left, s.box.top, s.box.right, s.box.bottom), list(s.ends), bool(s.lane), s.wire)
               for s in rest]
    snapshot = module.PreparedContacts(records, [fp.ref for fp in occ.geometry.footprints])
    for x in [10, 10.5, 15, 20, 10]:
        got = snapshot.contacts(candidate, x, 10, 0, 'U1', '1', 'S')
        occ.commit(item, replace(original, location=Location(x, 10)))
        current = judging(occ)
        monkeypatch.setattr(geometry, '_native', None)
        own = current._own_copper('U1', '1', 'S')
        assert got[0] == current._joined('U1', '1', 'S')
        assert got[1] == current._on_own_net_pad('U1', '1', 'S')
        assert {records[i][:4] + (tuple(records[i][5]),) for i in got[2]} == {
            (s.owner, s.kind, s.net, s.label, tuple(s.poly)) for s in own}
        assert got[3] == current._runs_on(own, 'U1', '1', 'S')
        assert got[4] == any(s.kind == 'through' for s in own)
        assert got[5] == all(s.lane or s.wire for s in own)
        monkeypatch.setattr(geometry, '_native', module)
        occ.lift({'U1'})


def test_prepared_contacts_keep_path_only_carried_shapes_out_of_contact_grid():
    module = geometry._native
    assert module is not None and hasattr(module, 'PreparedContacts')
    main = _shape('U1', 'pad', 'S', '1', (0, 0, 1, 1))
    carried = _shape('carried-via', 'through', 'S', '', (0.5, 0, 1.5, 1))
    candidate = module.PreparedCandidate([((1, 0, 0, 1, 0, 0),
                                          [main[:6] + main[7:], carried[:6] + carried[7:]])])
    rest = [_shape('carried-rest', 'through', 'S', '', (0.5, 0, 1.5, 1))]
    snapshot = module.PreparedContacts(rest, ['U1'])
    assert snapshot.contacts(candidate, 0, 0, 0, 'U1', '1', 'S')[0] is True
    snapshot.configure_contact_roles(candidate, [False], [[True, False]])
    expected = (False, False, [], False, False, True)
    assert snapshot.contacts(candidate, 0, 0, 0, 'U1', '1', 'S') == expected
    # A refused configuration cannot replace the valid membership snapshot.
    for r, m in [([], [[True, False]]), ([True], []), ([True], [[True]])]:
        with pytest.raises(ValueError, match='role dimensions'):
            snapshot.configure_contact_roles(candidate, r, m)
        assert snapshot.contacts(candidate, 0, 0, 0, 'U1', '1', 'S') == expected
    # Reusing the record with a different candidate shape layout is explicit
    # refusal rather than indexing a stale role table or inventing a join.
    with pytest.raises(ValueError, match='candidate identity'):
        snapshot.contacts(_candidate(module, main), 0, 0, 0, 'U1', '1', 'S')

    same_layout = module.PreparedCandidate([((1, 0, 0, 1, 0, 0),
                                          [main[:6] + main[7:], carried[:6] + carried[7:]])])
    with pytest.raises(ValueError, match='candidate identity'):
        snapshot.contacts(same_layout, 0, 0, 0, 'U1', '1', 'S')


def test_carried_member_shape_matches_python_contact_and_path_pool_split(monkeypatch):
    from dataclasses import replace
    from placemat.escapes import judging, search_near
    from placemat.score_delta import Delta
    from tests.fixtures import board_geometry, pad
    from tests.test_final_board import _placed
    from tests.test_surface_escapes import _part_of
    module = geometry._native
    assert module is not None and hasattr(module, 'PreparedContacts')
    parts = [_part_of('U1', 'u1', [pad('U1', 'u1', 1, 'S', 10, 10, 1, 1)], 10, 10),
             _part_of('U2', 'u2', [pad('U2', 'u2', 1, 'S', 20, 10, 1, 1)], 20, 10)]
    board, plan = _placed(board_geometry(parts))
    occ, item = plan.occupancy, parts[0]
    original = plan.placement('u1')
    own_pad = next(s for s in occ.items['U1'].shapes if s.kind == 'pad')
    carried = replace(own_pad, owner='carried-via', kind='through', label='')
    occ.carry('U1', [carried])
    # Contact pool excludes this carried owner, but path search still sees
    # it among the member's through shapes after a canonical commit.
    monkeypatch.setattr(geometry, '_native', None)
    current = judging(occ)
    assert not current._joined('U1', '1', 'S')
    assert not current._on_own_net_pad('U1', '1', 'S')
    assert current._own_copper('U1', '1', 'S') == []
    assert any(s.owner == 'carried-via' for s in search_near(occ))
    monkeypatch.setattr(geometry, '_native', module)
    occ.lift({'U1'})
    candidate = Delta(board, occ, item, plan.links, plan=plan).native_shapes([0], original.face)
    assert candidate is not None
    shapes = occ.candidate_shapes(item, original)[1]
    mask = [s.kind in ('pad', 'through') and s.owner == 'U1' for s in shapes]
    assert any(s.owner == 'carried-via' and not included for s, included in zip(shapes, mask))
    snapshot = module.PreparedContacts([], ['U1', 'U2'])
    snapshot.configure_contact_roles(candidate, [], [mask])
    assert snapshot.contacts(candidate, original.location.x, original.location.y, 0, 'U1', '1', 'S') == (
        False, False, [], False, False, True)
