"""NativeObstacles.first_move and tail_clear (native/src/giveway.rs): a via's
whole move, and a share's tail, judged in one call. Their marshalling is
tested here; that they choose what the Python loop chooses is tested in
the parity tests below."""
import pytest

placemat_native = pytest.importorskip("placemat_native")

_BOTH, _COPPER = 3, 1          # faces (front|back), layers (bit 0)


def _sq(cx, cy, half):
    return ((cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half))


def _shape(kind, poly, net, owner="o"):
    return (kind, 1, _COPPER, net, tuple(poly), owner, False, False, 0.0, False)


def _index(shapes):
    return placemat_native.NativeObstacles(shapes, 0.02, False, 0.1, 0.2, 0.2, {}, 1.0, 0.2, 0.25, 0.0)


def test_tail_clear_is_false_when_the_tail_meets_the_board_or_mine_and_true_otherwise():
    board = _index([_shape("pad", _sq(0.3, 0.0, 0.1), "B")])
    tail = _shape("copper", _sq(0.0, 0.0, 0.1), "A")
    assert board.tail_clear([tail], [], 0.2, []) is False
    assert board.tail_clear([tail], [], 0.2, [0]) is True               # the obstacle is set aside
    far = _index([_shape("pad", _sq(5.0, 0.0, 0.1), "B")])
    assert far.tail_clear([tail], [], 0.2, []) is True
    assert far.tail_clear([tail], [_shape("pad", _sq(0.3, 0.0, 0.1), "B")], 0.2, []) is False


def test_first_move_returns_the_index_of_the_first_offset_clear_of_mine():
    ring = _shape("through", _sq(0.0, 0.0, 0.3), "A")
    mine = [_shape("pad", _sq(0.6, 0.0, 0.3), "B")]
    board = _index([])
    offsets = [(0.3, 0.0), (0.0, 0.3), (-0.3, 0.0)]
    assert board.first_move([ring], offsets, 0.2, [], mine, (0.0, 0.0), None, None, None, 0) == 2
    assert board.first_move([ring], offsets, 0.2, [], mine, (0.0, 0.0), None, None, None, 3) is None


def test_first_move_redraws_the_tail_at_each_offset():
    ring = _shape("through", _sq(0.0, 0.0, 0.3), "A")
    board = _index([_shape("copper", _sq(0.0, 1.0, 0.3), "B")])
    proto = _shape("copper", _sq(0.0, 0.0, 0.1), "A")
    offsets = [(0.0, 1.0), (2.0, 0.0)]
    tail = (proto, (0.0, -1.0), 0.2, 8)
    assert board.first_move([ring], offsets, 0.2, [], [], (0.0, 0.0), None, None, tail, 0) == 1
    assert board.first_move([ring], offsets, 0.2, [0], [], (0.0, 0.0), None, None, tail, 0) == 0


def test_first_move_keeps_the_via_in_its_pad_and_off_what_it_first_met():
    ring = _shape("through", _sq(0.0, 0.0, 0.3), "A")
    board = _index([])
    offsets = [(5.0, 0.0), (-0.2, 0.0), (0.2, 0.0)]
    first = (_sq(-1.0, 0.0, 0.5), 0.2, 0.3)
    pad = (_sq(0.0, 0.0, 1.0), 0.3)
    assert board.first_move([ring], offsets, 0.2, [], [], (0.0, 0.0), first, pad, None, 0) == 2
