"""Unoutlined searches share a scoring frame without acquiring a physical edge."""
import dataclasses

import pytest

from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def fragment():
    fps = [footprint('J1', 10, 10, inst='j1', nets=('A', 'B')),
           footprint('R1', 40, 40, inst='r1', nets=('A', 'B'))]
    board = Board(board_geometry(fps), settings=dataclasses.replace(Settings(), cleanup_enabled=True))
    board.place(Part('j1'), at=Location(10, 10))
    board.place(Part('r1'))
    return board


def test_fragment_cleanup_has_a_fixed_diagnostic_frame(monkeypatch):
    board = fragment()
    plan = board.resolve()
    plan.occupancy.board_box = None
    original = Board._scorer
    seen = []

    def scorer(self, item, occ, *args, **kwargs):
        assert occ.board_box is None
        frame = occ.congestion_frame()
        assert frame is not None
        for box in self._scoring_pad_boxes(occ):
            assert frame.contains(box)
        seen.append(frame)
        return original(self, item, occ, *args, **kwargs)

    monkeypatch.setattr(Board, '_scorer', scorer)
    board._cleanup(plan.occupancy, plan)
    assert seen
    assert plan.occupancy.congestion_frame() == plan.occupancy.board_box
    assert not plan.occupancy.pending


def test_fragment_diagnostic_frame_is_restored_when_scoring_raises(monkeypatch):
    board = fragment()
    plan = board.resolve()
    plan.occupancy.board_box = None
    stop = RuntimeError('scoring cancelled')
    occupancies = []

    def scorer(self, item, occ, *args, **kwargs):
        assert occ.congestion_frame() is not None
        occupancies.append(occ)
        raise stop

    monkeypatch.setattr(Board, '_scorer', scorer)
    with pytest.raises(RuntimeError) as caught:
        board._cleanup(plan.occupancy, plan)
    assert caught.value is stop
    assert occupancies and all(occ.congestion_frame() is None and occ.board_box is None
                              for occ in occupancies)
