"""A track that would run through other nets' copper says all of it, in the order along its first leg from its start, and
whether each pad was already placed when the room planning first tried the track. Synthetic boards."""
import dataclasses

from placemat.finding_text import render
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import CopperLayer, Location, Near, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint

F = CopperLayer.F
GAP = 0.2


def _board(fps):
    s = dataclasses.replace(Settings(), place_envelope="physical")
    return Board(board_geometry(fps, width=60, height=60, silk_clearance=GAP, clearance=GAP), edge_margin=1.0,
                 settings=s, component_spacing=GAP)


def _fp(ref, x, nets):
    return footprint(ref, x, 20, w=2, h=1, inst=ref.lower(), nets=nets, excess=0.0, fab=(x - 1, 19.5, x + 1, 20.5))


def _not_drawn(plan):
    (f,) = [f for f in plan.findings if f.cause.value == "copper.not_drawn" and f.facts.get("variant") == "through"]
    return f


def test_a_leg_through_three_parts_names_all_of_them_along_the_leg():
    fps = [_fp("F1", 10, ("B", "A")), _fp("F2", 42, ("A", "B")),
           _fp("K3", 32, ("G", "H")), _fp("K1", 20, ("C", "D")), _fp("K2", 26, ("E", "G"))]
    b = _board(fps)
    for fp in fps:
        b.place(Part(fp.inst), at=Location(fp.location.x, fp.location.y))
    b.track(Net("A"), [PadRef(Part("f1"), 2), PadRef(Part("f2"), 1)], layer=F, why="straight through the three")
    f = _not_drawn(b.resolve())
    got = [(c["who"][0], c["label"]) for c in f.facts["blockers"]]
    assert got == [("K1", "1"), ("K1", "2"), ("K2", "1"), ("K2", "2"), ("K3", "1"), ("K3", "2")]
    assert f.facts["met"] == f.facts["blockers"][0]
    assert f.facts["leg"]["start"] == [10.4, 20.0] and f.facts["leg"]["end"] == [41.6, 20.0]
    assert render(f.cause, f.facts).endswith("it would run through K1 pad 1 (C) and 5 more") or "and 5 more" in render(f.cause, f.facts), render(f.cause, f.facts)


def test_a_blocker_is_said_to_have_been_placed_or_not_when_the_track_became_plannable():
    """F1 firm; S1 searched first and joined to F1 by a track past K, which stands on the way (firm, placed first); T,
    searched after S1, is hinted onto the way as well, and was not placed when the track was first tried."""
    fps = [_fp("F1", 10, ("B", "A")),
           footprint("S1", 36, 20, w=6, h=3, inst="s1", nets=("A", "C"), excess=0.0, fab=(33, 18.5, 39, 21.5)),
           _fp("K1", 20, ("D", "E")),
           footprint("T1", 28, 20, w=2, h=1, inst="t1", nets=("G", "H"), excess=0.0, fab=(27, 19.5, 29, 20.5))]
    b = _board(fps)
    b.place(Part("f1"), at=Location(10, 20))
    b.place(Part("k1"), at=Location(20, 20))
    b.place(Part("s1"), at=Near(Location(36, 20)))
    b.place(Part("t1"), at=Near(Location(28, 20)))
    b.track(Net("A"), [PadRef(Part("f1"), 2), PadRef(Part("s1"), 1)], layer=F, why="past k1")
    f = _not_drawn(b.resolve())
    by = {c["who"][0]: c["placed_when_plannable"] for c in f.facts["blockers"] if c["form"] == "pad"}
    assert by["K1"] is True
    assert by.get("T1", False) is False


def test_a_track_refused_when_it_could_first_be_planned_says_so_and_what_refused_it():
    """S1 searched, then T1 searched onto the track's first stretch. When S1 stands the track can be planned, but it runs
    through K1 (firm, further along), so no room is kept for it and T1 lands on it: the finding names T1 first along the
    leg, and says that no room was kept, from when, and that K1 refused it then."""
    fps = [_fp("F1", 10, ("B", "A")),
           footprint("S1", 36, 20, w=6, h=3, inst="s1", nets=("A", "C"), excess=0.0, fab=(33, 18.5, 39, 21.5)),
           _fp("K1", 28, ("D", "E")),
           footprint("T1", 18, 20, w=2, h=1, inst="t1", nets=("G", "H"), excess=0.0, fab=(17, 19.5, 19, 20.5))]
    b = _board(fps)
    b.place(Part("f1"), at=Location(10, 20))
    b.place(Part("k1"), at=Location(28, 20))
    b.place(Part("s1"), at=Near(Location(36, 20)))
    b.place(Part("t1"), at=Near(Location(18, 20)))
    b.track(Net("A"), [PadRef(Part("f1"), 2), PadRef(Part("s1"), 1)], layer=F, why="past k1")
    f = _not_drawn(b.resolve())
    assert f.facts["met"]["who"][0] == "T1" and f.facts["met"]["placed_when_plannable"] is False
    room = f.facts["room"]
    assert room["after"] == "s1"
    assert room["met"]["who"][0] == "K1" and "placed_when_plannable" not in room["met"]
    assert room["more"] == 1
    text = render(f.cause, f.facts)
    assert "no room was kept for it: it could be planned once s1 was placed, and then it ran through K1 pad 1 (D) and 1 more" \
        in text, text


def test_a_track_drawn_when_it_could_first_be_planned_says_nothing_of_its_room():
    fps = [_fp("F1", 10, ("B", "A")), _fp("F2", 42, ("A", "B")), _fp("K1", 20, ("C", "D"))]
    b = _board(fps)
    for fp in fps:
        b.place(Part(fp.inst), at=Location(fp.location.x, fp.location.y))
    b.track(Net("A"), [PadRef(Part("f1"), 2), PadRef(Part("f2"), 1)], layer=F, why="straight through k1")
    f = _not_drawn(b.resolve())
    assert "room" not in f.facts
    assert "no room" not in render(f.cause, f.facts)
