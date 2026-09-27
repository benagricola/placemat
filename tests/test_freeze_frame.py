"""What freeze writes puts an item where the lock would, after the anchor
turns: the offset and the rotation are the lock's own, in the anchor's
frame. Pure: synthetic boards."""
import pytest

import placemat
from placemat import freeze, lock
from placemat.layout import Board
from placemat.values import Face, Location, Part
from tests.fixtures import board_geometry, footprint


def _board(rotation, face):
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("C1", 26, 26, w=2, h=1, inst="c1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 20), rotation=rotation, face=face)
    return b


@pytest.mark.parametrize("face", [Face.FRONT, Face.BACK])
def test_a_frozen_item_lands_where_the_lock_puts_it_after_its_anchor_turns(face):
    b = _board(0, face)
    b.place(Part("c1"), face=face)
    plan = b.resolve()
    turn = plan.turns["c1"]
    entry = lock.entry_from_turn("c1", turn, "digest", "")
    assert entry.anchor is not None
    args = freeze.frozen_args(b, "c1", turn, False, entry=entry, why="'x'")
    names = {n: getattr(placemat, n) for n in placemat.__all__}
    at, rotation = eval(args["at"], names), eval(args["rotation"], names)
    turned = _board(90, face)
    turned.place(Part("c1"), at=at, rotation=rotation, face=face)
    frozen = turned.resolve()
    want, why = lock.placement_of(entry, frozen.occupancy)
    got = frozen.placement("c1")
    assert want is not None, why
    assert got.location.distance(want.location) < 1e-6
    assert got.rotation == want.rotation


def test_the_why_names_the_run_and_score_when_the_lock_has_them():
    e = lock.LockEntry("c1", ("U1", "1"), "front", (0.1, -2.5), 90.0, "front", "d", run="1a2b3c4d", score=812.5)
    assert freeze.why_text("the bypass by its pin", e, "2026-09-27") == \
        "the bypass by its pin; explore 1a2b3c4d: 812.5 mm, frozen 2026-09-27"
    old = lock.LockEntry("c1", ("U1", "1"), "front", (0.1, -2.5), 90.0, "front", "d")
    assert freeze.why_text("", old, "2026-09-27") == "explore: frozen 2026-09-27"
