"""Placement keeps room for the copper a script declares: a track or via declared between parts is planned provisionally,
so a part standing Beside another moves out of its way, a part searched after it keeps clear of it, and a Beside part that
a firm part placed before it refused is placed before that one. Synthetic boards."""
import dataclasses

import pytest

from placemat.geometry import poly_distance
from placemat.layout import Board, PlacementCollision
from placemat.settings import Settings
from placemat.values import Beside, CopperLayer, Edge, Location, Near, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint

F = CopperLayer.F
GAP = 0.2


def _settings(**kw):
    return dataclasses.replace(Settings(), place_envelope="physical", **kw)


def _board(fps, copper_room=True, **kw):
    return Board(board_geometry(fps, width=60, height=60, silk_clearance=GAP, clearance=GAP), edge_margin=1.0,
                 settings=_settings(place_copper_room=copper_room), component_spacing=GAP, **kw)


def _pads(plan, ref):
    return [s for s in plan.occupancy.items[ref].shapes if s.kind in ("pad", "through")]


def _distance_to_track(plan, ref):
    """The least distance from `ref`'s pads to the copper the plan drew."""
    tracks = [op for op in plan.copper if op.__class__.__name__ == "Track"]
    return min(poly_distance(p.poly, t.polygon) for p in _pads(plan, ref) for t in tracks)


def _beside_with_track(copper_room):
    """U1 with a track leaving its pad 1 northward, ending just past its north side; R1 beside it on the north side,
    wide enough that its own pad 1 stands 0.1 mm off the track's line at the standoff."""
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0, fab=(18.0, 19.0, 22.0, 21.0)),
           footprint("R1", 40, 40, w=2.6, h=1, inst="r1", nets=("C", "D"), excess=0.0, fab=(38.7, 39.5, 41.3, 40.5))]
    b = _board(fps, copper_room)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.NORTH))
    b.track(Net("A"), [PadRef(Part("u1"), 1), Location(18.6, 17.4)], layer=F, why="a track north of the pad")
    return b.resolve()


def test_a_part_beside_another_stands_clear_of_the_track_declared_past_it():
    plan = _beside_with_track(True)
    assert _distance_to_track(plan, "R1") >= GAP - 1e-4
    assert not [f for f in plan.findings if str(f).startswith("copper")], plan.findings


def test_without_room_the_part_stands_at_the_standoff_over_the_track():
    plan = _beside_with_track(False)
    assert _distance_to_track(plan, "R1") < GAP - 1e-4          # the squeeze the room prevents
    assert any(str(f).startswith("copper A") for f in plan.findings), plan.findings


def test_the_part_stands_as_near_as_the_track_allows():
    near = _beside_with_track(True).box("r1").bottom
    far = _beside_with_track(False).box("r1").bottom
    assert near < far - 0.05                                     # moved out, north is smaller y
    assert near > far - 2.0 + 1e-6                               # and within the reach


def _crowded(copper_room, keep_going=False):
    """Q, tall, stands east of Z (declared first); P stands north of Y, 0.1 mm off Q's side at its standoff, and moving
    north does not clear the tall part. Placing P first lets Q stand off it."""
    fps = [footprint("Y1", 20, 20, w=2, h=2, inst="y1", nets=("N1", "N2"), excess=0.0, fab=(19, 19, 21, 21)),
           footprint("Z1", 18.9, 13.25, w=4, h=2, inst="z1", nets=("N3", "N4"), excess=0.0, fab=(16.9, 12.25, 20.9, 14.25)),
           footprint("Q1", 22.1, 13.25, w=2, h=10.5, inst="q1", nets=("N5", "N6"), excess=0.0, fab=(21.1, 8.0, 23.1, 18.5)),
           footprint("P1", 40, 40, w=2, h=1, inst="p1", nets=("N7", "N8"), excess=0.0, fab=(39, 39.5, 41, 40.5))]
    b = _board(fps, copper_room, keep_going=keep_going)
    b.place(Part("y1"), at=Location(20, 20))
    b.place(Part("z1"), at=Location(18.9, 13.25))
    b.place(Part("q1"), at=Beside(Part("z1"), Edge.EAST))
    b.place(Part("p1"), at=Beside(Part("y1"), Edge.NORTH))
    return b.resolve()


def test_without_the_order_turned_the_two_collide():
    with pytest.raises(PlacementCollision) as e:
        _crowded(False)
    assert "P1" in str(e.value) and "Q1" in str(e.value)


def test_a_beside_part_refused_by_one_placed_before_it_is_placed_first_and_the_other_stands_off_it():
    plan = _crowded(True)
    assert not [f for f in plan.findings if f.cause.kind.value == "fixed"], plan.findings
    p = next(s for s in plan.steps if s.item == "p1")
    assert "placed before q1" in p.note
    # Q stands off Z by its standoff and, for P, a little further east
    assert plan.box("q1").left >= plan.box("p1").right + GAP - 1e-4


def test_a_part_searched_after_declared_copper_keeps_clear_of_it():
    """S, searched first (the bigger part), is joined to F by a track; T, searched next, would land on that track's
    way were it not planned ahead."""
    fps = [footprint("F1", 20, 20, w=2, h=1, inst="f1", nets=("B", "A"), excess=0.0, fab=(19, 19.5, 21, 20.5)),
           footprint("S1", 30, 30, w=6, h=3, inst="s1", nets=("A", "C"), excess=0.0, fab=(27, 28.5, 33, 31.5)),
           footprint("T1", 40, 40, w=2, h=1, inst="t1", nets=("D", "E"), excess=0.0, fab=(39, 39.5, 41, 40.5))]

    def run(room):
        b = _board(fps, room)
        b.place(Part("f1"), at=Location(20, 20))
        b.place(Part("s1"), at=Near(Location(30, 20)))
        b.place(Part("t1"), at=Near(Location(24, 20.0)))
        b.track(Net("A"), [PadRef(Part("f1"), 2), PadRef(Part("s1"), 1)], layer=F, why="joins the two")
        return b.resolve()
    with_room = run(True)
    assert _distance_to_track(with_room, "T1") >= GAP - 1e-4
    assert not with_room.findings, with_room.findings
    assert any("not drawn" in str(f) for f in run(False).findings)         # as before: the track met the part placed over it


def test_a_run_that_is_placed_again_reports_its_firm_items_once():
    lines = []
    fps = [footprint("Y1", 20, 20, w=2, h=2, inst="y1", nets=("N1", "N2"), excess=0.0, fab=(19, 19, 21, 21)),
           footprint("Z1", 18.9, 13.25, w=4, h=2, inst="z1", nets=("N3", "N4"), excess=0.0, fab=(16.9, 12.25, 20.9, 14.25)),
           footprint("Q1", 22.1, 13.25, w=2, h=10.5, inst="q1", nets=("N5", "N6"), excess=0.0, fab=(21.1, 8.0, 23.1, 18.5)),
           footprint("P1", 40, 40, w=2, h=1, inst="p1", nets=("N7", "N8"), excess=0.0, fab=(39, 39.5, 41, 40.5))]
    b = _board(fps, True)
    b.place(Part("y1"), at=Location(20, 20))
    b.place(Part("z1"), at=Location(18.9, 13.25))
    b.place(Part("q1"), at=Beside(Part("z1"), Edge.EAST))
    b.place(Part("p1"), at=Beside(Part("y1"), Edge.NORTH))
    b.resolve(progress=lines.append)
    assert len([l for l in lines if l.startswith("q1 ")]) == 1, lines
    assert len([l for l in lines if l.startswith("p1 ")]) == 1, lines


def test_a_beside_part_that_no_place_within_reach_clears_of_the_copper_is_said_with_its_facts():
    """The track runs on north beyond the reach: R1 stays at its standoff, and the finding names the copper."""
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0, fab=(18.0, 19.0, 22.0, 21.0)),
           footprint("R1", 40, 40, w=2.6, h=1, inst="r1", nets=("C", "D"), excess=0.0, fab=(38.7, 39.5, 41.3, 40.5))]
    b = _board(fps, True, keep_going=True)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.NORTH))
    b.track(Net("A"), [PadRef(Part("u1"), 1), Location(18.6, 8.0)], layer=F, why="a long track north of the pad")
    plan = b.resolve()
    room = [f for f in plan.findings if f.cause.value == "fixed.room"]
    assert len(room) == 1 and room[0].facts["item"] == "r1" and room[0].facts["copper"] == "track A"
    assert room[0].facts["side"] == "north" and room[0].facts["net"] == "A"
    assert plan.box("r1").bottom == pytest.approx(18.8, abs=1e-4)           # at the standoff


def test_provisional_copper_is_an_obstacle_only_where_it_applies():
    from placemat.copper import Track
    from placemat.layout import _shape_of
    from placemat.occupancy import Occupancy
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"))]
    occ = Occupancy(board_geometry(fps, width=60, height=60), 1.0)
    geom = occ._geometry(fps[0])
    room = _shape_of(Track("A", F, 0.2, Location(1, 1), Location(5, 1)))
    occ.set_rooms([room])
    assert room not in list(occ.obstacles(geom))
    occ.rooms_apply = True
    assert room in list(occ.obstacles(geom))


def test_a_copper_that_moved_between_passes_is_said_by_how_much():
    from placemat.copper import Track
    from placemat.layout import _rooms_moved, _shape_of
    a = dataclasses.replace(_shape_of(Track("A", F, 0.2, Location(1, 1), Location(5, 1))), owner="room track A")
    b = dataclasses.replace(_shape_of(Track("A", F, 0.2, Location(1, 1.5), Location(5, 1.5))), owner="room track A")
    assert _rooms_moved({0: [a]}, {0: [a]}, 0.001) == []
    ((key, mm),) = _rooms_moved({0: [a]}, {0: [b]}, 0.001)
    assert key == "track A" and mm == pytest.approx(0.5)


def test_a_part_refused_by_a_fixed_one_sends_the_part_it_is_aligned_with_back_to_the_box_without_keep_going():
    """P stands level with R1, which stands nearer U1 than the box put it (clear of U1's corner mark); at that height P is
    0.1 mm from the fixed F, which a move east does not clear. R1 goes back to the box's distance, P with it, and the run does
    not stop on a collision."""
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0, fab=(18.0, 19.0, 22.0, 21.0),
                     silk_boxes=[(18.0, 17.9, 18.6, 18.9)]),
           footprint("R1", 40, 40, w=2, h=1, inst="r1", nets=("C", "D"), excess=0.0, fab=(39, 39.5, 41, 40.5)),
           footprint("R2", 45, 40, w=2, h=1, inst="r2", nets=("E", "G"), excess=0.0, fab=(44, 39.5, 46, 40.5)),
           footprint("F1", 23.4, 19.9, w=2, h=2, inst="f1", nets=("H", "I"), excess=0.0, fab=(22.4, 18.9, 24.4, 20.9))]
    b = _board(fps, True)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("f1"), at=Location(23.4, 19.9))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.NORTH))
    b.place(Part("r2"), at=Beside(Part("r1"), Edge.EAST))
    plan = b.resolve()
    assert not [f for f in plan.findings if f.cause.value == "fixed.part"], plan.findings
    assert plan.box("r1").bottom == pytest.approx(17.9 - GAP, abs=1e-4)           # the box's distance, not the silk line's


def _two_searched_joined_by_a_pour(room):
    """S1 and S2, searched first (the bigger parts), are joined by a fitted pour of net A; T, searched after them, is
    drawn to the middle between them, where the pour must go."""
    fps = [footprint("S1", 20, 30, w=6, h=3, inst="s1", nets=("C", "A"), excess=0.0, fab=(17, 28.5, 23, 31.5)),
           footprint("S2", 36, 30, w=6, h=3, inst="s2", nets=("A", "D"), excess=0.0, fab=(33, 28.5, 39, 31.5)),
           footprint("T1", 28, 30, w=2, h=1, inst="t1", nets=("E", "G"), excess=0.0, fab=(27, 29.5, 29, 30.5))]
    b = _board(fps, room)
    b.place(Part("s1"), at=Location(20, 30))
    b.place(Part("s2"), at=Near(Location(36, 30)))
    b.place(Part("t1"), at=Near(Location(28, 30)))
    b.pour(Net("A"), [PadRef(Part("s1"), 2), PadRef(Part("s2"), 1)], layer=F, swallow_pads=True, why="joins the two")
    return b.resolve()


def test_a_part_searched_after_a_pour_joining_searched_parts_keeps_clear_of_it():
    from placemat.copper import Pour
    got = _two_searched_joined_by_a_pour(True)
    assert any(isinstance(c, Pour) for c in got.copper), got.findings
    assert not got.findings, got.findings
    assert not any("not drawn" in str(f) for f in got.findings)


def test_without_room_a_part_searched_after_the_pour_lands_where_it_cannot_be_drawn():
    from placemat.copper import Pour
    got = _two_searched_joined_by_a_pour(False)
    assert not any(isinstance(c, Pour) for c in got.copper) and any("not drawn" in str(f) for f in got.findings)
