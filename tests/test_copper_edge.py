"""Declared copper nearer the board's outline or a cutout than the copper-to-edge clearance is a copper.edge finding
when it is planned: KiCad's copper_edge_clearance (drc_test_provider_edge_clearance.cpp testAgainstEdge collides the
copper's shape with each Edge.Cuts shape at the clearance less the DRC epsilon, a touch at a clearance of 0). A loop
drawn from arcs is judged geometry.arc_sag further. The copper is drawn either way. Pure: synthetic boards."""
import math
import re

import pytest

from placemat.copper import Track
from placemat.cutouts import Circle, Slot
from placemat.layout import Board, copper_id
from placemat.values import CopperLayer, Corner, Cutout, Edge, Location, Net, PadRef, Part, Past, Priority
from tests.escape_fixtures import fan_board
from tests.fixtures import board_geometry
from tests.suggest_support import apply_and_resolve, resolve
from tests.test_past_obstacles import EDGE, SAG, W3A, _board, _part

VENT = Cutout(Circle(1.5), "vent", at=Location(20.0, 15.0))              # box x 19.25..20.75, y 14.25..15.75


def _edge(plan):
    return [f for f in plan.findings if f.cause.value == "copper.edge"]


def test_the_reported_case_a_3a_track_drawn_across_the_vent():
    b = _board(holes=[VENT])
    t = b.track(Net("VBUS"), [Location(20.0, 5.0), Location(20.0, 25.0)], layer=CopperLayer.B, width=W3A)
    plan = b.resolve()
    (f,) = _edge(plan)
    assert f.severity == "critical" and f.facts["key"] == copper_id(t)
    assert (f.facts["word"], f.facts["layer"], f.facts["net"]) == ("track", "B", "VBUS")
    assert f.facts["obstacle"] == {"form": "cutout", "name": "vent"} and f.facts["inside"] is False
    assert f.facts["gap_mm"] == 0.0 and f.facts["need_mm"] == EDGE and f.facts["sag_mm"] == SAG
    assert f.facts["rule"] == "copper_edge_clearance" and f.facts["sides"] == ["WEST", "EAST"]
    assert f.facts["at"][0] == pytest.approx(20.0) and f.facts["at"][1] in (pytest.approx(14.25), pytest.approx(15.75))
    assert re.fullmatch(r'track VBUS on B\.Cu: 0\.00 mm from cutout "vent" at \(20\.00, 1[45]\.[27]5\), under the '
                        r"board's 0\.40 mm copper-to-edge clearance", str(f)), str(f)
    assert any(isinstance(op, Track) and op.net == "VBUS" for op in plan.copper)          # drawn all the same


def test_the_reported_case_passed_with_past_is_clear():
    b = _board(holes=[VENT])
    b.track(Net("VBUS"), [Location(20.0, 5.0), Past([VENT], Edge.WEST), Location(20.0, 25.0)], layer=CopperLayer.B,
            width=W3A)
    assert _edge(b.resolve()) == []


@pytest.mark.parametrize("x, gap", [(0.4, 0.3), (0.5, None)], ids=["inside the clearance", "at it"])
def test_a_track_by_a_straight_outline_side(x, gap):
    b = _board()
    b.track(Net("SIG"), [Location(x, 5.0), Location(x, 25.0)], layer=CopperLayer.F)
    found = _edge(b.resolve())
    if gap is None:
        assert found == []
    else:
        (f,) = found
        assert f.facts["obstacle"] == {"form": "outline"} and f.facts["gap_mm"] == pytest.approx(gap)
        assert f.facts["sag_mm"] == 0.0 and f.facts["sides"] == [] and "the board's edge" in str(f)


@pytest.mark.parametrize("x, found", [(19.25 - EDGE - SAG / 2 - 0.1, 1), (19.25 - EDGE - SAG - 0.1, 0)],
                         ids=["within the arc allowance", "past it"])
def test_a_round_cutout_is_judged_with_the_arc_allowance(x, found):
    b = _board(holes=[VENT])
    b.track(Net("SIG"), [Location(x, 5.0), Location(x, 25.0)], layer=CopperLayer.F)
    assert len(_edge(b.resolve())) == found


def test_a_via_wholly_inside_a_cutout_lies_inside_it():
    b = _board(holes=[Cutout(Circle(3.0), "well", at=Location(20.0, 15.0))])
    b.via(Net("SIG"), at=Location(20.0, 15.0), size=0.6)
    (f,) = _edge(b.resolve())
    assert (f.facts["inside"], f.facts["gap_mm"], f.facts["word"], f.facts["layer"]) == (True, 0.0, "via", "")
    assert str(f) == 'via SIG: lies inside cutout "well"'


def test_a_pour_by_points_over_the_outline_is_a_finding_and_a_plane_is_not():
    b = _board()
    b.pour(Net("SIG"), [Location(-1.0, 5.0), Location(5.0, 5.0), Location(5.0, 10.0), Location(-1.0, 10.0)],
           layer=CopperLayer.F)
    b.plane(Net("GND"), [CopperLayer.B])
    found = _edge(b.resolve())
    assert [(f.facts["word"], f.facts["obstacle"]["form"], f.facts["gap_mm"]) for f in found] == [("pour", "outline", 0.0)]


def test_a_fitted_pour_by_the_edge_keeps_its_own_clearance():
    pads = [_part("PA", "pa", "SIG", 1.9, 10.0), _part("PB", "pb", "SIG", 1.9, 20.0)]
    b = _board(pads)
    b.pour(Net("SIG"), [PadRef(Part("pa"), 1), PadRef(Part("pb"), 1)], layer=CopperLayer.F, swallow_pads=True)
    assert _edge(b.resolve()) == []


def test_a_pour_over_a_whole_hole_is_0_from_it():
    """Review focus 4: KiCad collides the filled shape with the hole's Edge.Cuts shapes."""
    b = _board(holes=[VENT])
    b.pour(Net("SIG"), [Location(15.0, 10.0), Location(25.0, 10.0), Location(25.0, 20.0), Location(15.0, 20.0)],
           layer=CopperLayer.F)
    (f,) = _edge(b.resolve())
    assert f.facts["obstacle"] == {"form": "cutout", "name": "vent"} and f.facts["gap_mm"] == 0.0
    assert f.facts["inside"] is False


def test_with_no_edge_clearance_only_a_touch_is_a_finding():
    """Review focus 5: a clearance of 0 still reports copper on the edge (KiCad collides at max(0, clearance - eps))."""
    b = _board(holes=[VENT], edge_clearance=0.0, margin=0.0)
    b.track(Net("SIG"), [Location(19.1, 5.0), Location(19.1, 25.0)], layer=CopperLayer.F)   # 0.05 mm clear of the hole
    b.track(Net("VBUS"), [Location(20.0, 5.0), Location(20.0, 25.0)], layer=CopperLayer.B)  # across it
    assert [f.facts["net"] for f in _edge(b.resolve())] == ["VBUS"]


def test_a_module_frame_is_not_an_edge():
    """Review focus 1: a fragment's frame is never written to Edge.Cuts."""
    b = _board(draw=False)
    b.track(Net("SIG"), [Location(0.0, 5.0), Location(0.0, 25.0)], layer=CopperLayer.F)
    assert _edge(b.resolve()) == []



def _rounded(radius=2.0, holes=()):
    b = Board(board_geometry([], width=40.0, height=30.0, extra_nets=["VBUS", "SIG", "GND"]), edge_margin=EDGE)
    b.rect(width=40.0, height=30.0, radius=radius, holes=list(holes))
    return b


@pytest.mark.parametrize("gap, found", [(0.41, 0), (0.39, 1)])
def test_a_straight_side_of_a_rounded_board_takes_no_arc_allowance(gap, found):
    """The arc allowance is the arc legs': KiCad passes a track 0.41 mm off the straight west side of a rounded board."""
    b = _rounded()
    b.track(Net("SIG"), [Location(gap + 0.1, 5.0), Location(gap + 0.1, 25.0)], layer=CopperLayer.F)
    got = _edge(b.resolve())
    assert len(got) == found and all(f.facts["sag_mm"] == 0.0 for f in got)


@pytest.mark.parametrize("gap, found", [(0.41, 0), (0.39, 1)])
def test_a_straight_side_of_a_slot_takes_no_arc_allowance(gap, found):
    """An 8 x 2 slot at (20, 15): its straight north side is y = 14."""
    b = _rounded(radius=0.0, holes=[Cutout(Slot(8.0, 2.0), "slot", at=Location(20.0, 15.0))])
    y = 14.0 - gap - 0.1
    b.track(Net("SIG"), [Location(5.0, y), Location(35.0, y)], layer=CopperLayer.F)
    got = _edge(b.resolve())
    assert len(got) == found and all(f.facts["sag_mm"] == 0.0 for f in got)


def test_a_convex_outline_arc_is_judged_on_its_chords_alone():
    """A rounded corner's chords stand inside the board, nearer the copper than the curve KiCad judges, so the chord's
    own gap already errs short: no allowance on top. A via 0.425 mm from the true curve, mid-chord, is about 0.408 mm
    from the chord."""
    b = _rounded()
    a = math.radians(217.5)                         # mid-way along a 15-degree chord of the NW corner's arc
    d = 2.0 - 0.3 - 0.425
    b.via(Net("SIG"), at=Location(2.0 + d * math.cos(a), 2.0 + d * math.sin(a)), size=0.6)
    assert _edge(b.resolve()) == []


def test_a_track_in_two_pieces_across_one_cutout_is_one_finding():
    """Bridged under a track of another net, a track is drawn as pieces; across the vent twice, it is one finding."""
    b = _board(holes=[VENT])
    b.track(Net("VBUS"), [Location(20.0, 5.0), Location(20.0, 25.0)], layer=CopperLayer.F, bridge=True)
    b.track(Net("SIG"), [Location(5.0, 15.0), Location(35.0, 15.0)], layer=CopperLayer.F, priority=Priority.HIGH)
    plan = b.resolve()
    vbus = [f for f in _edge(plan) if f.facts["net"] == "VBUS"]
    assert len([op for op in plan.copper if isinstance(op, Track) and op.net == "VBUS"]) >= 2
    assert len(vbus) == 1 and vbus[0].facts["gap_mm"] == 0.0


def test_a_finger_by_the_outline_is_a_finding():
    b = _board()
    b.finger(Net("SIG"), layer=CopperLayer.F, from_=(0.3, 10.0), to=(0.3, 20.0), width=0.4)
    (f,) = _edge(b.resolve())
    assert (f.facts["word"], f.facts["obstacle"]) == ("finger", {"form": "outline"})


def test_a_fit_frame_is_not_an_edge():
    """Review focus 1: a fit= fragment's frame is never written to Edge.Cuts."""
    pa = _part("PA", "pa", "SIG", 10.0, 10.0)
    b = Board(board_geometry([pa], extra_nets=["SIG"]), edge_margin=0.0)
    b.rect(fit=True, draw=False, margin=0.0)
    b.place(Part("pa"), at=pa.location)
    b.track(Net("SIG"), [Location(9.5, 10.0), Location(9.5, 25.0)], layer=CopperLayer.F)
    assert _edge(b.resolve()) == []


def test_a_track_from_a_lane_counts_its_declared_waypoints():
    """A lane's own points are not waypoints; the points the script gives after it are, so a Past is offered only to a
    lane track that has none."""
    b = fan_board()
    esc = b.escape(Part("mcu"), [45, 44], turn=Corner.NW, why="a fan")
    bare = b.track(Net("N45"), [esc[45]], layer=CopperLayer.F)
    bent = b.track(Net("N44"), [esc[44], Location(5.0, 5.0), Location(5.0, 2.0)], layer=CopperLayer.F)
    assert (bare.declared["waypoints"], bent.declared["waypoints"]) == (0, 1)


IMPORTS = "from placemat import board, CopperLayer, Cutout, Edge, Location, Net, Past\nfrom placemat.cutouts import Circle\n"
ACROSS = '''board.rect(width=60, height=60, holes=[Cutout(Circle(1.5), "vent", at=Location(30, 30))])
board.track(Net("OUT"), [Location(30, 20), Location(30, 40)], layer=CopperLayer.B, width=1.37)
'''


def test_a_track_across_a_cutout_is_offered_a_past_off_it_on_each_side_and_the_first_clears_it(tmp_path):
    board, plan, path = resolve(tmp_path, ACROSS, imports=IMPORTS)
    (f,) = _edge(plan)
    texts = [s.text for s in f.suggestions]
    assert texts == ["Pass cutout `vent` on its west side with a Past waypoint",
                     "Pass cutout `vent` on its east side with a Past waypoint"], texts
    board2, plan2 = apply_and_resolve(tmp_path, plan, f.suggestions[0].id, path)
    assert 'Past([board.cutout("vent")], Edge.WEST)' in path.read_text()
    assert _edge(plan2) == []
