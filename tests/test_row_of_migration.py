"""Migration check (docs/superpowers/specs/2026-09-29-missing-intent-relations-design.md,
"Verification"): a stack of small parts down a part's own east side, as
docs/audits/2026-09-29-layout-scripts.md section 3 (R2, "rows off a part")
describes (Monitoring_layout.py:101-110, "a row fanned about the middle of
pins 7 and 8"; the general pattern: several small parts stacked off a
part's envelope, gap apart). Unrolled by hand below as `_hand_placed()`,
the way a script wrote it before `row(of=)` existed: each item's envelope
box a gap east of the reference part's, and a gap south of the previous
item's, the first flush with the reference part's own north edge.
`board.row(items, Edge.EAST, of=u1, align=Along.START)` says the same
relation as intent; this asserts the two land in the same place, within
0.01 mm."""
import pytest

from placemat.layout import Board
from placemat.values import Along, Edge, Location, Part
from tests.fixtures import board_geometry, footprint

ROW = ("p_a", "p_b", "p_c")   # small parts down u1's east side, north-flush


def _board():
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="u1", nets=("A", "B"))] + [
        footprint(name.upper(), 0, 0, w=2, h=1, inst=name, nets=("A", "GND")) for name in ROW]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def _hand_placed():
    """The hand arithmetic, unrolled: every item's envelope box the same
    gap east of u1's own; each one's envelope box a gap south of the one
    before it (the first flush with u1's own north edge) - envelope to
    envelope throughout, so the default gap of 0.0 is courtyards touching
    (each already carries its own 0.1 mm excess, which is where the visible
    0.2 mm between bodies comes from)."""
    b = _board()
    b.place(Part("u1"), at=Location(20.0, 20.0), rotation=0, why="the reference part")
    u1_env = b.envelope(Part("u1"), rotation=0)               # box at the origin: a size, not a place
    x_off = 20.0 + u1_env.right                                # every item's envelope, this far east of u1's
    cursor_y = 20.0 + u1_env.top                                # align=START: the stack starts at u1's own north edge
    gap = 0.0                                                  # envelope to envelope: courtyards touching
    for name in ROW:
        env = b.envelope(Part(name), rotation=0)
        top = cursor_y + gap
        origin = Location(x_off - env.left, top - env.top)
        b.place(Part(name), at=origin, rotation=0, why="down u1's east side, north-flush")
        cursor_y = top + env.height
    return b.resolve()


def _row_of_placed():
    b = _board()
    b.place(Part("u1"), at=Location(20.0, 20.0), rotation=0, why="the reference part")
    b.row([Part(name) for name in ROW], Edge.EAST, of=Part("u1"), align=Along.START, rotation=0,
         why="down u1's east side, north-flush")
    return b.resolve()


def test_row_of_matches_the_hand_computed_row_within_0_01mm():
    hand, intent = _hand_placed(), _row_of_placed()
    for name in ROW:
        a, b = hand.box(name), intent.box(name)
        assert a.left == pytest.approx(b.left, abs=0.01)
        assert a.top == pytest.approx(b.top, abs=0.01)
        assert a.right == pytest.approx(b.right, abs=0.01)
        assert a.bottom == pytest.approx(b.bottom, abs=0.01)
