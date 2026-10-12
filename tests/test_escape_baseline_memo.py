"""Lifted boards of one occupancy share what they judged of their rest pads (escapes._BaselineMemo): every judgement
taken from it is the one a fresh judgement gives."""
from dataclasses import replace
import math

from placemat import escapes
from placemat.layout import Board
from placemat.occupancy import ban_shape
from placemat.settings import Settings
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint, pad, track
from tests.test_surface_escapes import _part_of, _round_pad


def _board():
    item = _part_of('P1', 'p1', [_round_pad('P1', 'p1', 1, 'S', 30, 30, 0.5)], 30, 30)
    target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, 30, 0.5, 0.5)], 10, 30)
    other = footprint('R1', 40, 40, inst='r1', nets=('S', 'Q'))
    far = footprint('R2', 50, 10, inst='r2', nets=('Q', 'Z'))
    ring = []
    for index in range(48):
        angle = 2 * math.pi * index / 48
        x, y = 30 + 1.3 * math.cos(angle), 30 + 1.3 * math.sin(angle)
        ring.append(track('Z', x, y, x + 0.001, y, w=0.1))
    board = Board(board_geometry([item, target, other, far], width=60, height=60, copper=ring), keep_going=True,
                  settings=replace(Settings(), cleanup_enabled=False))
    board.rect(width=60, height=60)
    for part in (item, target, other, far):
        board.place(Part(part.inst), at=part.location)
    plan = board.resolve()
    plan.occupancy.add_copper([ban_shape('via exclusion', ((28, 28), (32, 28), (32, 32), (28, 32)), None, ('Z',))])
    return board, plan.occupancy


def _judged(delta):
    return {key: (delta.regions[key], delta._base_way(key), delta._base_walls(key)) for key in delta.nets}


def test_a_memo_judgement_is_a_fresh_one_from_lift_to_lift(monkeypatch):
    board, occ = _board()
    geometry = {fp.ref: fp for fp in board.geometry.footprints}
    reused = []
    real = escapes.Escapes._verdict

    def verdict(self, *a, **kw):
        reused.append(0)
        return real(self, *a, **kw)
    monkeypatch.setattr(escapes.Escapes, '_verdict', verdict)
    steps = [('R2', Location(50, 20)), ('R1', Location(40, 45)), ('R2', Location(50, 10)), ('P1', Location(34, 30))]
    judged_fresh = judged_memo = 0
    for ref, to in steps:
        occ.lift({ref})
        before = len(reused)
        memo = _judged(escapes.EscapeDelta(occ, {ref}, native=escapes.native_judge()))
        judged_memo += len(reused) - before
        monkeypatch.setattr(escapes, 'BASELINE_MEMO', False)
        before = len(reused)
        fresh = _judged(escapes.EscapeDelta(occ, {ref}, native=escapes.native_judge()))
        judged_fresh += len(reused) - before
        monkeypatch.setattr(escapes, 'BASELINE_MEMO', True)
        assert memo == fresh, ref
        occ.commit(geometry[ref], replace(occ._geometry(geometry[ref]).reference, location=to))
    assert judged_memo < judged_fresh, (judged_memo, judged_fresh)
