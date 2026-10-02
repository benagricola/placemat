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


def test_a_via_that_left_its_pad_is_moved_as_a_move_is():
    from placemat.kicad.write import _given_way
    board, groups = _board()
    a = Action("leave", "m via 0", "m", "m", "GND", (19.1, 21.9), (18.2, 21.9), None, None)
    _given_way(board, SimpleNamespace(given_way=[a]), groups)
    assert _copper(board) == [("PCB_TRACK", 10.0, 10.0), ("PCB_TRACK", 19.1, 20.0), ("PCB_VIA", 18.2, 21.9)]


def test_the_tail_a_via_gave_way_drew_joins_the_cells_group():
    """KiCad applies a clearance rule that holds within a cell (`A.memberOf('m') && B.memberOf('m')`) to the
    items of its group: a tail the plan draws for the cell's via is the cell's copper, so it is in the group."""
    from placemat.copper import Track
    from placemat.kicad.write import _given_way, _group_given_way_tracks, draw_copper
    from placemat.values import CopperLayer, Location
    board, groups = _board()
    tail = Track("GND", CopperLayer.F, 0.2, Location(19.1, 20.0), Location(18.6, 21.9))
    a = Action("move", "m via 0", "m", "m", "GND", (19.1, 21.9), (18.6, 21.9), tail, ((19.1, 21.9), (19.1, 20.0)))
    plan = SimpleNamespace(given_way=[a])
    _given_way(board, plan, groups)
    draw_copper(board, [tail])
    _group_given_way_tracks(board, plan, groups)
    drawn = [t for t in board.GetTracks() if type(t).__name__ == "PCB_TRACK"
             and abs(t.GetStart().x / 1e6 - 19.1) < 1e-6 and abs(t.GetEnd().x / 1e6 - 18.6) < 1e-6]
    assert len(drawn) == 1
    assert drawn[0].GetParentGroup() is not None and drawn[0].GetParentGroup().GetName() == "m"
