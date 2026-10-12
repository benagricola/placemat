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
