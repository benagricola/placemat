"""route --adopt --partial: an open net's new copper kept island by island,
each island that joins two of the net's pads, or a pad and a plane."""
import dataclasses

from placemat import routes
from placemat.board_geometry import CopperItem
from placemat.values import Box, CopperLayer, Location
from tests.fixtures import board_geometry, footprint, rect
from tests.test_routes import _track, _via

F, B = CopperLayer.F, CopperLayer.B


def _board():
    """Net X on U1.2 (11.4, 10), R1.1 (19.4, 16), C1.1 (29.4, 10) and P1.1
    (7.4, 30); a plane of X on B.Cu round (5, 30)."""
    parts = [footprint("U1", 10, 10, w=4, h=1, inst="u1", nets=("A", "X")),
             footprint("R1", 20, 16, w=2, h=1, inst="r1", nets=("X", "B")),
             footprint("C1", 30, 10, w=2, h=1, inst="c1", nets=("X", "C")),
             footprint("P1", 8, 30, w=2, h=1, inst="p1", nets=("X", "D"))]
    plane = rect(4, 30, 3, 3)
    zone = CopperItem("zone", "X", frozenset([B]), (plane,), Box.of_points(plane))
    return board_geometry(parts, copper=[zone], width=40, height=40)


def _routed(placed):
    return dataclasses.replace(placed, copper=tuple(placed.copper) + (
        _track("X", (11.4, 10.0), (15.0, 10.0)), _track("X", (15.0, 10.0), (19.4, 16.0)),    # U1.2 - R1.1: kept
        _track("X", (29.4, 10.0), (33.0, 10.0)),                                              # C1.1 to nothing
        _track("X", (7.4, 30.0), (5.0, 30.0)), _via("X", (5.0, 30.0))))                     # P1.1 to the plane


def test_islands_joining_two_terminals_are_kept_and_a_dangling_one_is_not():
    placed = _board()
    kept = routes.adoptable(placed, _routed(placed), ["X"], still_open={"X": 1}, partial=True)
    assert len(kept) == 1 and kept[0].partial
    e = kept[0]
    assert len(e.tracks) == 3 and len(e.vias) == 1                  # the two islands, not the dangling track
    assert set(e.parts) == {"u1", "r1", "p1"}


def test_without_partial_an_open_net_keeps_nothing():
    placed = _board()
    skipped = {}
    assert routes.adoptable(placed, _routed(placed), ["X"], still_open={"X": 1}, skipped=skipped) == []
    assert "open" in skipped["X"]


def test_a_shorted_net_keeps_nothing_partial_or_not():
    placed = _board()
    assert routes.adoptable(placed, _routed(placed), ["X"], still_open={"X": 1}, shorted=["X"], partial=True) == []


def test_a_second_partial_adoption_adds_an_entry_and_a_whole_one_replaces_them(tmp_path):
    placed = _board()
    (first,) = routes.adoptable(placed, _routed(placed), ["X"], still_open={"X": 1}, partial=True)
    second = dataclasses.replace(first, adopted="later")
    assert routes.merged([first], [second]) == [first, second]
    whole = dataclasses.replace(first, partial=False, adopted="whole")
    assert routes.merged([first, second], [whole]) == [whole]
    path = tmp_path / "Board_layout.routes.json"
    routes.write(path, [first, second])
    assert [e.partial for e in routes.read(path)] == [True, True]


def test_every_entry_of_a_net_resolves_on_its_own_and_is_released_together(tmp_path):
    from placemat.layout import Board
    from placemat.values import Part
    placed = _board()
    (first,) = routes.adoptable(placed, _routed(placed), ["X"], still_open={"X": 1}, partial=True)
    b = Board(placed, edge_margin=0.5)
    for inst, at in (("u1", (10, 10)), ("r1", (20, 16)), ("c1", (30, 10)), ("p1", (8, 30))):
        b.place(Part(inst), at=Location(*at))
    plan = b.resolve(routes=[first, dataclasses.replace(first, adopted="later")])
    assert sorted(plan.adopted.values()) == ["held", "held"]
    script = tmp_path / "Board_layout.py"
    routes.write(routes.path_for(script), [first, first])
    assert routes.release(script, ["X"]) == [] and routes.read(routes.path_for(script)) == []
