"""place(face=Face.EITHER): a searched item lets the search try both faces,
scores each spot as it scores any, and keeps the face the spot is on. Pure."""
import dataclasses

import pytest

from placemat import lock, reuse
from placemat.cutouts import Circle
from placemat.explore import Explore
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Cell, CopperLayer, Face, Location, Near, Part, Turned
from tests.fixtures import board_geometry, footprint


def _board(extra=(), cells=(), keep_going=True, width=40, height=40, blocker=True, **settings):
    """A front part B1 that fills the middle of the board, and the part R1 to search."""
    fps = ([footprint("B1", 20, 20, w=30, h=30, inst="b1", nets=("N", "M"))] if blocker else []) + list(extra)
    return Board(board_geometry(fps, cells=cells, width=width, height=height), edge_margin=0.5,
                 keep_going=keep_going, settings=dataclasses.replace(Settings(), **settings))


def _r1(face, **kw):
    return footprint("R1", 5, 5, inst="r1", nets=("X", "Y"), **kw)


def _declare(b, face, at=Near(Location(20, 20), radius=3.0)):
    b.place(Part("b1"), at=Location(20, 20))
    b.place(Part("r1"), at=at, face=face)
    return b.resolve()


def test_an_item_with_no_room_on_the_front_but_room_on_the_back_places_on_the_back():
    plan = _declare(_board([_r1(None)]), Face.EITHER)
    assert plan.placement("r1").face is Face.BACK
    assert not [f for f in plan.findings if f.kind == "unplaced"]
    assert "back face" in next(s for s in plan.steps if s.item == "r1").note


def test_the_same_item_pinned_to_the_front_is_unplaced():
    plan = _declare(_board([_r1(None)]), Face.FRONT)
    assert plan.placement("r1") is None


def test_equal_room_prefers_the_front():
    b = _board([_r1(None)], blocker=False)
    b.place(Part("r1"), at=Near(Location(20, 20), radius=3.0), face=Face.EITHER)
    assert b.resolve().placement("r1").face is Face.FRONT


def test_the_front_wins_a_tie_at_no_back_face_cost():
    b = _board([_r1(None)], blocker=False, score_back_face=0.0)
    b.place(Part("r1"), at=Near(Location(20, 20), radius=3.0), face=Face.EITHER)
    assert b.resolve().placement("r1").face is Face.FRONT


def _linked(face, **settings):
    """R1 shares net N with B1's west pad: its best spot is on that pad, under B1's courtyard,
    which only the back face can take; the front spots are a courtyard's width further off."""
    fps = [footprint("R1", 5, 5, inst="r1", nets=("N", "Y"))]
    b = _board(fps, **settings)
    b.place(Part("b1"), at=Location(20, 20))
    b.place(Part("r1"), face=face)
    return b.resolve()


def test_a_back_spot_that_saves_enough_wire_beats_the_front():
    plan = _linked(Face.EITHER, score_back_face=0.01)
    assert plan.placement("r1").face is Face.BACK


def test_a_dearer_back_face_keeps_the_item_on_the_front():
    plan = _linked(Face.EITHER, score_back_face=1000.0)
    assert plan.placement("r1").face is Face.FRONT


def test_the_face_does_not_change_what_a_pinned_item_does():
    assert _linked(Face.FRONT).placement("r1") == _linked(Face.FRONT, score_back_face=1000.0).placement("r1")
    assert _linked(Face.BACK).placement("r1").face is Face.BACK


def test_a_front_keepout_sends_a_surface_part_to_the_back():
    b = _board([_r1(None)])
    # the middle of B1 is a free spot on the back; on the front it is kept clear by a rule area
    b.keepout(Circle(8.0), "front only", at=Location(20, 20), excludes=("parts",), layers=(CopperLayer.F,),
              why="kept off the front here")
    b.place(Part("b1"), at=Location(5, 5))
    b.place(Part("r1"), at=Near(Location(20, 20), radius=2.0), face=Face.EITHER)
    plan = b.resolve()
    assert plan.placement("r1").face is Face.BACK
    assert plan.placement("r1").location.distance(Location(20, 20)) <= 2.0


def test_a_through_hole_cell_is_judged_against_the_other_faces_parts():
    # B1's courtyard is over the whole middle: a surface cell takes the back there, a cell with
    # through-hole leads cannot - its leads reach the front, under B1's courtyard - on either face
    def run(through):
        fps = [footprint("C1", 5, 5, w=2, h=1, inst="c1.u1", cell="c1", nets=("X", "Y"), through=through)]
        b = _board(fps, cells=["c1"])
        b.place(Part("b1"), at=Location(20, 20))
        b.place(Cell("c1"), at=Near(Location(20, 20), radius=3.0), face=Face.EITHER)
        return b.resolve()
    surface, through = run(False), run(True)
    assert surface.placement("c1").face is Face.BACK
    assert through.placement("c1") is None
    assert [f for f in through.findings if f.kind == "unplaced"]


def test_a_through_hole_part_takes_the_back_face_of_a_front_keepout_no_more_than_the_front():
    fps = [footprint("J1", 5, 5, w=2, h=1, inst="j1", nets=("A", "B"), through=True)]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, keep_going=True)
    b.keepout(Circle(6.0), "front only", at=Location(20, 20), excludes=("parts",), layers=(CopperLayer.F,),
              why="kept off the front here")
    b.place(Part("j1"), at=Near(Location(20, 20), radius=2.0), face=Face.EITHER)
    assert b.resolve().placement("j1") is None


def test_a_cell_places_on_either_face_and_keeps_its_inner_flip_rules():
    fps = [footprint("C1", 5, 5, w=2, h=1, inst="c1.u1", cell="c1", nets=("X", "Y"))]
    b = _board(fps, cells=["c1"])
    b.place(Part("b1"), at=Location(20, 20))
    b.place(Cell("c1"), at=Near(Location(20, 20), radius=3.0), face=Face.EITHER)
    plan = b.resolve()
    assert plan.placement("c1").face is Face.BACK
    assert plan.occupancy.items["C1"].reference.face is Face.BACK


def test_either_is_the_string_either_too():
    b = _board([_r1(None)])
    b.place(Part("r1"), at=Near(Location(20, 20), radius=3.0), face="either")
    assert b.resolve().placement("r1") is not None


@pytest.mark.parametrize("face", [None, "both", 0])
def test_a_face_that_is_not_front_back_or_either_is_refused(face):
    b = _board([_r1(None)])
    with pytest.raises(TypeError):
        b.place(Part("r1"), face=face)


@pytest.mark.parametrize("at", [Location(10, 10), Location(10, None)])
def test_either_with_a_decided_or_line_position_is_refused(at):
    b = _board([_r1(None)])
    with pytest.raises(ValueError, match="searched"):
        b.place(Part("r1"), at=at, face=Face.EITHER)


def test_either_with_an_edge_is_refused():
    from placemat.values import Edge, OnEdge
    b = _board([_r1(None)])
    with pytest.raises(ValueError, match="searched"):
        b.place(Part("r1"), at=OnEdge(Edge.NORTH), face=Face.EITHER)


def test_either_with_a_facing_rotation_is_refused():
    from placemat.values import Edge, Facing, PadRef
    b = _board([_r1(None)])
    with pytest.raises(ValueError, match="face"):
        b.place(Part("r1"), face=Face.EITHER, rotation=Facing(PadRef(Part("r1"), 1), Edge.NORTH))


def test_a_declaration_without_either_digests_as_before():
    a, b = _board([_r1(None)]), _board([_r1(None)])
    a.place(Part("r1"), face=Face.FRONT)
    b.place(Part("r1"))
    assert reuse.canonical(a._intents[0]) == reuse.canonical(b._intents[0])
    c = _board([_r1(None)])
    c.place(Part("r1"), face=Face.EITHER)
    assert reuse.canonical(c._intents[0]) != reuse.canonical(a._intents[0])


def test_replaying_keeps_the_face_the_first_run_chose():
    def make():
        b = _board([_r1(None)])
        b.place(Part("b1"), at=Location(20, 20))
        b.place(Part("r1"), at=Near(Location(20, 20), radius=3.0), face=Face.EITHER)
        return b
    first = make().resolve()
    again = make().resolve(reuse=first.reuse)
    assert again.reuse["reused"] == len(first.reuse["steps"])
    assert again.placement("r1") == first.placement("r1") and again.placement("r1").face is Face.BACK
    assert again.occupancy.items["R1"].reference.face is Face.BACK


def test_a_lock_keeps_the_face_the_search_chose():
    def make():
        b = _board([_r1(None)], cleanup_enabled=False)
        b.place(Part("b1"), at=Location(20, 20))
        b.place(Part("r1"), at=Near(Location(20, 20), radius=3.0), face=Face.EITHER)
        return b
    b = make()
    plan = b.resolve(explore=Explore(seed=3, focus=frozenset({"r1"})))
    assert plan.placement("r1").face is Face.BACK
    entries = lock.entries(b, plan, ["r1"])
    held = make().resolve(lock=entries)
    assert held.placement("r1") == plan.placement("r1")
    assert "held by lock" in held.step("r1").note


def test_turned_rotation_is_allowed_with_either():
    b = _board([_r1(None)])
    b.place(Part("b1"), at=Location(20, 20))
    b.place(Part("r1"), at=Near(Location(20, 20), radius=3.0), face=Face.EITHER, rotation=Turned(Part("b1"), 90.0))
    assert b.resolve().placement("r1") is not None


@pytest.mark.parametrize("scored", [False, True])
def test_a_native_sweep_of_either_face_is_the_python_sweep(scored, monkeypatch):
    """Each face's scan is swept natively when it can be: the same scans, and so the same plan."""
    pytest.importorskip("placemat_native")
    from placemat import placer

    def run(on):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        seen = []

        class Recorded(placer.ScanResult):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                seen.append(self)
        monkeypatch.setattr(placer, "ScanResult", Recorded)
        monkeypatch.setattr("placemat.layout.ScanResult", Recorded)
        plan = _linked(Face.EITHER, score_back_face=0.01) if scored else _declare(_board([_r1(None)]), Face.EITHER)
        return ([(r.chosen, r.tried, list(r.rejected.items()), list(r.reasons.items()), list(r.blockers.items()),
                  getattr(r, "score", None)) for r in seen],
                [(s.item, s.placement, s.note) for s in plan.steps])
    assert run(True) == run(False)
