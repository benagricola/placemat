"""The write does to a stamped cell's own vias what they did as the cell
was placed (giveway.py): a shared or dropped via and its tail are taken off
the board, a moved one is moved and its old tail taken off."""
from types import SimpleNamespace

import pytest

pytest.importorskip("pcbnew")

from placemat.giveway import Action  # noqa: E402
from tests.conftest import needs_kicad  # noqa: E402

pytestmark = [needs_kicad]


def _board():
    import pcbnew
    board = pcbnew.BOARD()
    net = pcbnew.NETINFO_ITEM(board, "GND")
    board.Add(net)
    g = pcbnew.PCB_GROUP(board)
    g.SetName("m")
    board.Add(g)

    def mm(x, y):
        return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(mm(19.1, 21.9))
    via.SetNet(net)
    board.Add(via)
    g.AddItem(via)
    tail = pcbnew.PCB_TRACK(board)
    tail.SetStart(mm(19.1, 20.0))
    tail.SetEnd(mm(19.1, 21.9))
    tail.SetNet(net)
    board.Add(tail)
    g.AddItem(tail)
    other = pcbnew.PCB_TRACK(board)             # the cell's other copper stays
    other.SetStart(mm(10.0, 10.0))
    other.SetEnd(mm(12.0, 10.0))
    other.SetNet(net)
    board.Add(other)
    g.AddItem(other)
    return board, {"m": g}


def _copper(board):
    import pcbnew
    return sorted((type(t).__name__, round(t.GetStart().x / 1e6, 3), round(t.GetStart().y / 1e6, 3))
                  for t in board.GetTracks())


def test_a_shared_via_and_its_old_tail_are_taken_off():
    from placemat.kicad.write import _given_way
    board, groups = _board()
    a = Action("share", "m via 0", "m", "m", "GND", (19.1, 21.9), (19.1, 22.85), None,
               ((19.1, 21.9), (19.1, 20.0)))
    _given_way(board, SimpleNamespace(given_way=[a]), groups)
    assert _copper(board) == [("PCB_TRACK", 10.0, 10.0)]


def test_a_moved_via_is_moved_and_its_old_tail_taken_off():
    from placemat.kicad.write import _given_way
    board, groups = _board()
    a = Action("move", "m via 0", "m", "m", "GND", (19.1, 21.9), (19.1, 22.05), None,
               ((19.1, 21.9), (19.1, 20.0)))
    _given_way(board, SimpleNamespace(given_way=[a]), groups)
    assert _copper(board) == [("PCB_TRACK", 10.0, 10.0), ("PCB_VIA", 19.1, 22.05)]


def test_a_via_shared_on_its_spot_keeps_its_tail():
    from placemat.kicad.write import _given_way
    board, groups = _board()
    a = Action("share", "m via 0", "m", "m", "GND", (19.1, 21.9), (19.1, 21.95), None, None)
    _given_way(board, SimpleNamespace(given_way=[a]), groups)
    assert _copper(board) == [("PCB_TRACK", 10.0, 10.0), ("PCB_TRACK", 19.1, 20.0)]
