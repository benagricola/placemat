"""Declared copper nearer the board's outline or a cutout than the copper-to-edge clearance is a copper.edge finding
when it is planned: KiCad's copper_edge_clearance (drc_test_provider_edge_clearance.cpp testAgainstEdge collides the
copper's shape with each Edge.Cuts shape at the clearance less the DRC epsilon, a touch at a clearance of 0). A loop
drawn from arcs is judged geometry.arc_sag further. The copper is drawn either way. Pure: synthetic boards."""
import re

import pytest

from placemat.copper import Track
from placemat.cutouts import Circle
from placemat.layout import Board, copper_id
from placemat.values import CopperLayer, Cutout, Edge, Location, Net, PadRef, Part, Past
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
