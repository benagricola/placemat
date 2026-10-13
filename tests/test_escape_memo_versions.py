"""What lifted boards judged of their rest pads serves a later lifted board whose shapes round a pad are equal, the
boards between them however they differed: the baseline memo's earlier verdicts (escapes._BaselineMemo.earlier) and
the native memo's lifted searches and facts (prepared_escape.memo_of). Each answer is the one a fresh judgement gives."""
from dataclasses import replace

from placemat import escapes, prepared_escape
from placemat.prepared_escape import memo_of, prepare
from placemat.score_delta import Delta
from placemat.values import Face, Location
from tests.conftest import needs_native
from tests.test_escape_baseline_memo import _board, _judged
from tests.test_prepared_escape_cache import scene


def _put_back(occ, part):
    """Lift `part` and commit it where it stood: equal shapes, new objects."""
    occ.lift({part.ref})
    occ.commit(part, occ._geometry(part).reference)


def test_an_earlier_verdict_serves_a_board_with_equal_shapes_on_the_region(monkeypatch):
    board, occ = _board()
    geometry = {fp.ref: fp for fp in board.geometry.footprints}
    calls = []
    real_verdict, real_earlier = escapes.Escapes._verdict, escapes._BaselineMemo.earlier
    use_earlier = [True]

    def verdict(self, *a, **kw):
        calls.append(0)
        return real_verdict(self, *a, **kw)

    def earlier(self, *a):
        return real_earlier(self, *a) if use_earlier[0] else None
    monkeypatch.setattr(escapes.Escapes, '_verdict', verdict)
    monkeypatch.setattr(escapes._BaselineMemo, 'earlier', earlier)

    def judged(ref, with_earlier=True):
        occ.lift({ref})
        use_earlier[0] = with_earlier
        before = len(calls)
        memo = _judged(escapes.EscapeDelta(occ, {ref}, native=escapes.native_judge()))
        count = len(calls) - before
        use_earlier[0] = True
        monkeypatch.setattr(escapes, 'BASELINE_MEMO', False)
        fresh = _judged(escapes.EscapeDelta(occ, {ref}, native=escapes.native_judge()))
        monkeypatch.setattr(escapes, 'BASELINE_MEMO', True)
        assert memo == fresh, ref
        occ.commit(geometry[ref], occ._geometry(geometry[ref]).reference)
        return count

    # Each lift puts the part back as new shapes, so the other part's pads are judged again on the next lift; from the
    # third lift on, the board round them is equal to one judged before.
    counts = [judged(ref) for ref in ('R1', 'P1', 'R1', 'P1')]
    without = [judged(ref, with_earlier=False) for ref in ('R1', 'P1')]
    assert counts[2] + counts[3] < without[0] + without[1], (counts, without)


@needs_native
def test_a_native_memo_entry_serves_a_later_lifted_board_with_equal_shapes():
    board, plan, delta = scene()
    occ = delta.occ
    a = next(fp for fp in board.geometry.footprints if fp.ref == 'A')
    m = delta.item
    poses = [(11, 11), (12, 10), (24, 10)]

    def scores(delta, native_memo=True):
        prepared_escape.NATIVE_MEMO = native_memo
        try:
            prepared, reason = prepare(delta, (0,), Face.FRONT, rest_cache=True)
        finally:
            prepared_escape.NATIVE_MEMO = True
        assert prepared is not None, reason
        base = occ._geometry(m).reference
        return [prepared.evaluate(replace(base, location=Location(x, y)), 0, inspect=True) for x, y in poses]

    memo = memo_of(occ)
    first = scores(delta)
    made, taken, _ = memo.counts()
    assert made > 0
    # The same rest board again, after other lifted boards: A put back as new shapes, B lifted and put back.
    occ.unlift({'M'})
    _put_back(occ, a)
    _put_back(occ, next(fp for fp in board.geometry.footprints if fp.ref == 'B'))
    occ.lift({'M'})
    again = Delta(board, occ, m, plan.links, plan=plan)
    assert scores(again) == first == scores(again, native_memo=False)
    made_after, taken_after, _ = memo.counts()
    assert made_after == made and taken_after > taken


def _ringed(owner):
    """The baseline memo test's board, with the ring of tracks round P1's pad owned by `owner` and R1 off net S."""
    import math
    from placemat.layout import Board
    from placemat.settings import Settings
    from placemat.values import Part
    from tests.fixtures import board_geometry, footprint, pad, track
    from tests.test_surface_escapes import _part_of, _round_pad
    item = _part_of('P1', 'p1', [_round_pad('P1', 'p1', 1, 'S', 30, 30, 0.5)], 30, 30)
    target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, 30, 0.5, 0.5)], 10, 30)
    other = footprint('R1', 40, 40, inst='r1', nets=('Y', 'Q'))
    far = footprint('R2', 50, 10, inst='r2', nets=('Q', 'Z'))
    ring = []
    for index in range(48):
        angle = 2 * math.pi * index / 48
        x, y = 30 + 1.3 * math.cos(angle), 30 + 1.3 * math.sin(angle)
        ring.append(track('Z', x, y, x + 0.001, y, w=0.1, owner=owner))
    board = Board(board_geometry([item, target, other, far], width=60, height=60, copper=ring), keep_going=True,
                  settings=replace(Settings(), cleanup_enabled=False))
    board.rect(width=60, height=60)
    for part in (item, target, other, far):
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    return board, plan


def test_copper_of_a_lifted_owner_is_off_the_memo_board_and_back_on_when_it_returns(monkeypatch):
    # R2 owns the ring of tracks round P1's pad. Lifted, R2 takes its copper off the board as a verdict reads it, so P1
    # gets out; put back, the ring walls P1 again, though no shape of R2's own is near P1.
    board, plan = _ringed('R2')
    occ = plan.occupancy

    def judged(ref):
        memo = _judged(escapes.EscapeDelta(occ, {ref}, native=escapes.native_judge()))
        monkeypatch.setattr(escapes, 'BASELINE_MEMO', False)
        fresh = _judged(escapes.EscapeDelta(occ, {ref}, native=escapes.native_judge()))
        monkeypatch.setattr(escapes, 'BASELINE_MEMO', True)
        return memo, fresh
    occ.lift({'R2'})
    memo, fresh = judged('R2')
    assert memo == fresh and memo[('P1', '1')][1] is escapes.Way.SURFACE
    occ.unlift({'R2'})
    occ.lift({'R1'})
    memo, fresh = judged('R1')
    assert fresh[('P1', '1')][1] is escapes.Way.WALLED
    assert memo == fresh
    # The native rest cache takes its ways from the same memo: a surface with it scores R1 as one judging every pad.
    r1 = next(fp for fp in board.geometry.footprints if fp.ref == 'R1')
    delta = Delta(board, occ, r1, plan.links, plan=plan)
    delta.escape_native = escapes.native_judge()
    cached, reason = prepare(delta, (0,), Face.FRONT, rest_cache=True)
    plain, _ = prepare(delta, (0,), Face.FRONT)
    assert cached is not None and plain is not None, reason
    pose = occ._geometry(r1).reference
    assert cached.evaluate(pose, 0, inspect=True) == plain.evaluate(pose, 0, inspect=True)
