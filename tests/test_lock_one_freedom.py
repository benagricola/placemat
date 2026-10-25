"""A lock entry on an item with one freedom left (on a line, along an edge):
the run holds it at the entry's spot when that spot is on its freedom,
drifts along the freedom when the spot is taken, and releases the entry
when the spot is off its freedom."""
import dataclasses

from placemat import lock
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Centre, Edge, Location, OnEdge, PadRef, Part, X
from tests.fixtures import board_geometry, footprint


def _board(wall=None):
    fps = [footprint("U1", 10, 10, w=8, h=4, inst="mcu", nets=("A", "B")),
           footprint("R1", 60, 60, w=2, h=1, inst="r1", nets=("A", "X")),
           footprint("R2", 60, 62, w=2, h=1, inst="r2", nets=("B", "Y")),
           footprint("W1", 70, 70, w=2, h=1, inst="wall", nets=("W", "V"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0,
              settings=dataclasses.replace(Settings(), cleanup_enabled=False))
    b.place(Part("mcu"), at=Location(25, 25), rotation=0)
    if wall is not None:
        b.place(Part("wall"), at=Location(*wall), rotation=0)
    b.place(Part("r1"), at=Centre(X(PadRef(Part("mcu"), 1)), None))
    b.place(Part("r2"), at=OnEdge(Edge.NORTH))
    return b


def _entry(b, key, x, y, rotation=0.0):
    i = next(i for i in b._placements() if i.key == key)
    return lock.LockEntry(key, None, None, (x, y), rotation, "front", lock.declaration_digest(b, i))


def _at(plan, key):
    p = plan.placement(key)
    return round(p.location.x, 4), round(p.location.y, 4)


def test_an_item_on_a_line_is_held_at_its_locked_spot_on_the_line():
    free = _board().resolve()
    x, y = _at(free, "r1")
    plan = _board().resolve(lock=[_entry(_board(), "r1", x, 45.0)])
    assert _at(plan, "r1") == (x, 45.0)
    assert "held by lock" in plan.step("r1").note


def test_an_item_on_an_edge_is_held_at_its_locked_spot_on_the_edge():
    free = _board().resolve()
    x, y = _at(free, "r2")
    plan = _board().resolve(lock=[_entry(_board(), "r2", 45.0, y, free.placement("r2").rotation)])
    assert _at(plan, "r2") == (45.0, y)
    assert "held by lock" in plan.step("r2").note


def test_a_locked_spot_off_the_line_releases_the_entry_and_the_line_places_the_item():
    free = _board().resolve()
    x, y = _at(free, "r1")
    plan = _board().resolve(lock=[_entry(_board(), "r1", x + 2.0, 45.0)])
    assert _at(plan, "r1") == (x, y)
    assert "lock: released" in plan.step("r1").note and "off its line" in plan.step("r1").note


def test_a_taken_spot_on_the_line_drifts_along_the_line_and_says_so():
    free = _board().resolve()
    x, _ = _at(free, "r1")
    plan = _board(wall=(x, 45.0)).resolve(lock=[_entry(_board(wall=(x, 45.0)), "r1", x, 45.0)])
    px, py = _at(plan, "r1")
    assert px == x and py != 45.0 and abs(py - 45.0) < 5.0
    assert "lock: drifted" in plan.step("r1").note
