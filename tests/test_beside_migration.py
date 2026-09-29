"""Migration check (docs/superpowers/specs/2026-09-29-missing-intent-relations-design.md,
"Verification"): a module's row of pull-ups, placed by hand as a helper's
`beside()` does it (docs/audits/2026-09-29-layout-scripts.md, the most
common coordinate pattern). `beside(part, 1, prev, 1, PITCH, 0.0, rot, why)` places
`part`'s pad 1 at `(prev's pad 1) + (PITCH, 0.0)`, `PITCH` the previous
resistor's drawn envelope width plus the board's silk gap - unrolled below
as `_hand_placed()`. `at=Beside(prev, Edge.EAST, align=PadRef(prev, 1),
gap=GAP)` says the same relation as intent; this asserts the two land in
the same place, within 0.01 mm."""
import pytest

from placemat.layout import Board
from placemat.values import Beside, Edge, Location, PadRef, Part, Pin, X, Y
from tests.fixtures import board_geometry, footprint

GAP = 0.2     # the board's silk-to-silk clearance
ROW = ("r_a", "r_b", "r_c", "r_d", "r_e")   # the pull-ups, west to east


def _board():
    fps = [footprint(name.upper(), 0, 0, w=1.5, h=0.6, inst=name,
                     nets=("V3V3", name.upper() + "_SIG"))
           for name in ROW]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def _hand_placed():
    """The hand arithmetic, unrolled: each pull-up's pad
    1 (V3V3) lands PITCH east of the previous one's pad 1, PITCH the
    previous part's drawn envelope width plus the silk gap."""
    b = _board()
    b.place(Part(ROW[0]), at=Location(10.0, 20.0), rotation=0, why="the row's first pull-up at the origin")
    for i in range(1, len(ROW)):
        prev_box = b.envelope(Part(ROW[i - 1]), rotation=0)
        pitch = prev_box.width + GAP
        ref = PadRef(Part(ROW[i - 1]), 1)
        b.place(Part(ROW[i]), at=Pin(1, X(ref, pitch), Y(ref, 0.0)), rotation=0,
               why="the next pull-up a silk gap east, V3V3 in line")
    return b.resolve()


def _beside_placed():
    b = _board()
    b.place(Part(ROW[0]), at=Location(10.0, 20.0), rotation=0, why="the row's first pull-up at the origin")
    for i in range(1, len(ROW)):
        b.place(Part(ROW[i]),
               at=Beside(Part(ROW[i - 1]), Edge.EAST, align=PadRef(Part(ROW[i - 1]), 1), gap=GAP),
               rotation=0, why="the next pull-up a silk gap east, V3V3 in line")
    return b.resolve()


def test_beside_matches_the_hand_computed_row_within_0_01mm():
    hand, intent = _hand_placed(), _beside_placed()
    for name in ROW:
        a, b = hand.box(name), intent.box(name)
        assert a.left == pytest.approx(b.left, abs=0.01)
        assert a.top == pytest.approx(b.top, abs=0.01)
        assert a.right == pytest.approx(b.right, abs=0.01)
        assert a.bottom == pytest.approx(b.bottom, abs=0.01)
    for name in ROW:
        hp, ip = hand.occupancy.pad_location(name.upper(), "1"), intent.occupancy.pad_location(name.upper(), "1")
        assert (hp.x, hp.y) == pytest.approx((ip.x, ip.y), abs=0.01)
