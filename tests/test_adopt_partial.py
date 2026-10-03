"""route --adopt --partial: an open net's new copper kept island by island,
each island that joins two of the net's pads, or a pad and a plane."""
import dataclasses

from placemat.refusals import Refusal
from placemat import routes
from placemat.board_geometry import CopperItem
from placemat.values import Box, CopperLayer, Location
from tests.fixtures import board_geometry, footprint, rect
from tests.test_routes import _parts, _track, _via

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


def test_the_islands_are_counted_for_the_adopt_line():
    placed = _board()
    counts = {}
    routes.adoptable(placed, _routed(placed), ["X"], still_open={"X": 1}, partial=True, counts=counts)
    assert counts["X"] == {"kept": 2, "joined": 4, "dropped": 1}    # U1.2 and R1.1; P1.1 and the plane
    assert routes.island_line("X", counts["X"], 1) == \
        "X: 2 island(s) kept, joining 4 of its separate pieces; 1 dropped (leading nowhere, or joining nothing " \
        "new); still 1 open"


def test_new_copper_ending_on_the_scripts_plane_drop_is_kept():
    """A router track from a pad to a via the script put in the net's plane
    joins a pad and the plane; its end meets copper that is not new."""
    placed = _board()
    placed = dataclasses.replace(placed, copper=tuple(placed.copper) + (_via("X", (5.0, 30.0)),))   # the script's drop
    routed = dataclasses.replace(placed, copper=tuple(placed.copper) + (_track("X", (7.4, 30.0), (5.0, 30.0)),))
    (e,) = routes.adoptable(placed, routed, ["X"], still_open={"X": 1}, partial=True)
    assert len(e.tracks) == 1 and not e.vias


def test_new_copper_reaching_a_pad_through_the_scripts_track_joins_it():
    placed = _board()
    placed = dataclasses.replace(placed, copper=tuple(placed.copper) + (_track("X", (19.4, 16.0), (19.4, 20.0)),))
    routed = dataclasses.replace(placed, copper=tuple(placed.copper) + (_track("X", (11.4, 10.0), (11.4, 20.0)),
                                                                        _track("X", (11.4, 20.0), (19.4, 20.0))))
    (e,) = routes.adoptable(placed, routed, ["X"], still_open={"X": 1}, partial=True)
    assert len(e.tracks) == 2                  # U1.2 to R1.1, the last stretch the script's own


def _pass1(placed):
    """U1.2 to R1.1 round a corner at (15, 10), (15, 16)."""
    return dataclasses.replace(placed, copper=tuple(placed.copper) + (
        _track("X", (11.4, 10.0), (15.0, 10.0)), _track("X", (15.0, 10.0), (15.0, 16.0)),
        _track("X", (15.0, 16.0), (19.4, 16.0))))


def _placed_board(placed):
    from placemat.layout import Board
    from placemat.values import Part
    b = Board(placed, edge_margin=0.5)
    for inst, at in (("u1", (10, 10)), ("r1", (20, 16)), ("c1", (30, 10)), ("p1", (8, 30))):
        b.place(Part(inst), at=Location(*at))
    return b


def test_a_later_island_tied_to_an_earlier_ones_copper_holds():
    placed = _board()
    r1 = _pass1(placed)
    (first,) = routes.adoptable(placed, r1, ["X"], still_open={"X": 1}, partial=True)
    r2 = dataclasses.replace(r1, copper=tuple(r1.copper) + (_track("X", (29.4, 10.0), (29.4, 13.0)),
                                                             _track("X", (29.4, 13.0), (15.0, 13.0))))
    (second,) = routes.adoptable(r1, r2, ["X"], still_open={"X": 1}, partial=True)     # C1.1 to pass 1's middle
    plan = _placed_board(placed).resolve(routes=routes.merged([first], [second], held=[True]))
    assert sorted(plan.adopted.values()) == ["held", "held"], plan.adopted


def test_the_pass_that_closes_a_net_keeps_the_islands_that_held():
    placed = _board()
    r1 = _pass1(placed)
    (first,) = routes.adoptable(placed, r1, ["X"], still_open={"X": 1}, partial=True)
    closing = dataclasses.replace(first, partial=False, adopted="closing")
    assert routes.merged([first], [closing], held=[True]) == [first, closing]


def test_an_entry_that_did_not_hold_is_replaced_by_the_next():
    placed = _board()
    (first,) = routes.adoptable(placed, _pass1(placed), ["X"], still_open={"X": 1}, partial=True)
    stale = dataclasses.replace(first, adopted="stale")
    again = dataclasses.replace(first, adopted="again")
    assert routes.merged([stale], [again], held=[False]) == [again]


def test_an_island_joining_only_what_is_already_joined_is_dropped():
    """A stub from a pad to script copper that already reaches that pad
    joins nothing new."""
    placed = _board()
    placed = dataclasses.replace(placed, copper=tuple(placed.copper) + (_track("X", (19.4, 16.0), (19.4, 20.0)),))
    routed = dataclasses.replace(placed, copper=tuple(placed.copper) + (_track("X", (19.4, 20.0), (22.0, 20.0)),
                                                                        _track("X", (22.0, 20.0), (19.4, 16.0))))
    assert routes.adoptable(placed, routed, ["X"], still_open={"X": 1}, partial=True) == []


def test_each_dropped_island_is_counted():
    placed = _board()
    routed = dataclasses.replace(placed, copper=tuple(placed.copper) + (
        _track("X", (29.4, 10.0), (33.0, 10.0)), _track("X", (7.4, 30.0), (7.4, 34.0))))      # two stubs
    counts = {}
    routes.adoptable(placed, routed, ["X"], still_open={"X": 1}, partial=True, counts=counts)
    assert counts["X"]["dropped"] == 2


def test_a_track_ending_in_the_nets_pour_on_its_layer_reaches_the_plane():
    placed = _board()
    routed = dataclasses.replace(placed, copper=tuple(placed.copper) + (
        _track("X", (7.4, 30.0), (4.0, 30.0), w=0.2),))                  # P1.1 into the plane, on B.Cu below
    routed = dataclasses.replace(routed, copper=tuple(
        dataclasses.replace(c, layers=frozenset([B])) if c.kind == "track" else c for c in routed.copper))
    placed = dataclasses.replace(placed, footprints=tuple(
        dataclasses.replace(fp, pads=tuple(dataclasses.replace(p, layers=frozenset([F, B])) for p in fp.pads))
        for fp in placed.footprints))
    routed = dataclasses.replace(routed, footprints=placed.footprints)
    (e,) = routes.adoptable(placed, routed, ["X"], still_open={"X": 1}, partial=True)
    assert len(e.tracks) == 1


def test_an_end_on_a_zone_of_the_net_holds_on_the_next_run():
    """A zone is refilled round what is there, and a run's occupancy holds
    no fills: an end that met the net's zone is not held to meeting it."""
    from tests.test_routes import _occupancy
    placed = board_geometry(_parts(), width=40, height=40, extra_nets=())
    pour = rect(16, 10, 3, 3)
    zone = CopperItem("zone", "X", frozenset([F]), (pour,), Box.of_points(pour))
    placed = dataclasses.replace(placed, copper=tuple(placed.copper) + (zone,))
    routed = dataclasses.replace(placed, copper=tuple(placed.copper) + (_track("X", (11.4, 10.0), (16.0, 10.0)),))
    (e,) = routes.entries_from(placed, routed, ["X"])
    assert not any(p.get("meets") for t in e.tracks for p in (t["a"], t["b"]))
    assert not isinstance(routes.resolve(e, _occupancy(), 0.001), Refusal)


def test_the_entries_a_pass_replaces_are_named():
    placed = _board()
    (first,) = routes.adoptable(placed, _pass1(placed), ["X"], still_open={"X": 1}, partial=True)
    held, stale = dataclasses.replace(first, adopted="held"), dataclasses.replace(first, adopted="stale")
    again = dataclasses.replace(first, adopted="again")
    assert routes.replaced([held, stale], [again], held=[True, False]) == [stale]
