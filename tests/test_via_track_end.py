"""A via intent as a track's end: the track ends at the via's centre, found
or typed, and is left out with a finding when the via found no spot. Pure."""
import pytest

from placemat import FreeSpot
from placemat.copper import Track, Via
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("GND", "SIG")),
           footprint("R1", 20, 30, w=2, h=1, inst="r1", nets=("GND", "V3"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 30))
    return b


def test_a_track_ends_at_a_found_via():
    b = _board()
    v = b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND"), tail=False))
    b.track(Net("GND"), [v, PadRef(Part("r1"), "GND")], layer=CopperLayer.B)
    plan = b.resolve()
    (via,) = [c for c in plan.copper if isinstance(c, Via)]
    back = [c for c in plan.copper if isinstance(c, Track) and c.layer is CopperLayer.B]
    assert back and any(p.distance(via.at) < 1e-6 for t in back for p in (t.start, t.end))


def test_a_track_ends_at_a_typed_via():
    b = _board()
    v = b.via(Net("GND"), at=Location(25, 25))
    b.track(Net("GND"), [PadRef(Part("r1"), "GND"), v], layer=CopperLayer.B)
    plan = b.resolve()
    back = [c for c in plan.copper if isinstance(c, Track) and c.layer is CopperLayer.B]
    assert any(p.distance(Location(25, 25)) < 1e-6 for t in back for p in (t.start, t.end))


def test_a_track_through_a_via_that_found_nowhere_is_left_out_with_a_finding():
    b = _board()
    v = b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND"), radius=0.05))
    b.track(Net("GND"), [v, PadRef(Part("r1"), "GND")], layer=CopperLayer.B)
    b.via(Net("V3"), at=Location(30, 30))
    plan = b.resolve()
    assert not [c for c in plan.copper if isinstance(c, Track) and c.layer is CopperLayer.B]
    assert any("found no spot" in f and "track GND" in f for f in plan.findings)
    assert [c for c in plan.copper if isinstance(c, Via) and c.net == "V3"]


def test_an_intent_that_is_not_a_via_is_refused_as_a_track_end():
    b = _board()
    t = b.track(Net("GND"), [PadRef(Part("u1"), "GND"), Location(10, 10)], layer=CopperLayer.F)
    with pytest.raises(TypeError, match="not a via"):
        b.track(Net("GND"), [t, PadRef(Part("r1"), "GND")], layer=CopperLayer.B)


def test_a_track_through_a_searched_parts_via_is_planned_after_it():
    b = Board(board_geometry([footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("GND", "SIG")),
                              footprint("R1", 20, 30, w=2, h=1, inst="r1", nets=("GND", "V3"))],
                             width=40, height=40), edge_margin=0.5)
    b.place(Part("u1"))
    b.place(Part("r1"), at=Location(20, 30))
    v = b.via(Net("GND"), at=FreeSpot(near=PadRef(Part("u1"), "GND")))
    b.track(Net("GND"), [v, PadRef(Part("r1"), "GND")], layer=CopperLayer.B)
    plan = b.resolve()
    (via,) = [c for c in plan.copper if isinstance(c, Via)]
    back = [c for c in plan.copper if isinstance(c, Track) and c.layer is CopperLayer.B]
    assert any(p.distance(via.at) < 1e-6 for t in back for p in (t.start, t.end))
