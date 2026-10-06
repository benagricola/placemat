"""A courtyard over another part's hole follows the board's KiCad severity for it: `npth_inside_courtyard` for an
unplated hole, `pth_inside_courtyard` for a plated lead (drc_test_provider_courtyard_clearance.cpp). At "error",
KiCad's default, it is refused; at "warning" or "ignore" a firm placement may stand there, as KiCad accepts it.
A searched part keeps off the hole whatever the severity."""
import dataclasses

import pytest

from placemat.geometry import polys_overlap
from placemat.layout import Board, PlacementCollision
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Face, Location, Near, Part
from tests.fixtures import board_geometry, footprint

# J1 on the back with an unplated peg at its centre; J2 on the front, its pads clear of the peg when the two
# share a centre (pads 3.4 mm either side), its courtyard over it.
PEG = 1.0


def _pegged(cx=10.0, cy=10.0):
    return dataclasses.replace(footprint("J1", cx, cy, w=8, h=3, inst="j1", nets=("A", "B"), face=Face.BACK),
                               npth=((Location(cx, cy), PEG),))


def _front(cx=40.0, cy=40.0):
    return footprint("J2", cx, cy, w=8, h=3, inst="j2", nets=("C", "D"))


def _occ(fps, severities=None, **kw):
    g = board_geometry(fps, width=60, height=60)
    return g, Occupancy(g, edge_margin=0.0, settings=Settings(drc_severities=dict(severities or {})), **kw)


OVER_PEG = Placement(Location(10.0, 10.0), 0.0, Face.FRONT)


def test_a_firm_courtyard_over_an_npth_is_refused_at_kicad_s_default_severity():
    g, occ = _occ([_pegged(), _front()])
    why = occ.legal(g.footprint("J2"), OVER_PEG, by_corners=True)
    assert str(why) == "J2 courtyard sits over a npth (J1)", why


@pytest.mark.parametrize("severity", ["warning", "ignore"])
def test_a_firm_courtyard_over_an_npth_stands_when_the_board_s_severity_is_not_error(severity):
    g, occ = _occ([_pegged(), _front()], {"npth_inside_courtyard": severity})
    assert occ.legal(g.footprint("J2"), OVER_PEG, by_corners=True) is None


def test_a_firm_part_whose_npth_lies_under_a_placed_courtyard_stands_both_ways():
    g, occ = _occ([_pegged(cx=40.0, cy=40.0), _front(cx=10.0, cy=10.0)], {"npth_inside_courtyard": "warning"})
    over = Placement(Location(10.0, 10.0), 0.0, Face.BACK)
    assert occ.legal(g.footprint("J1"), over, by_corners=True) is None
    g, occ = _occ([_pegged(cx=40.0, cy=40.0), _front(cx=10.0, cy=10.0)])
    assert "sits over a npth" in str(occ.legal(g.footprint("J1"), over, by_corners=True))


def test_a_searched_courtyard_keeps_off_an_npth_at_severity_warning():
    g, occ = _occ([_pegged(), _front()], {"npth_inside_courtyard": "warning"})
    why = occ.legal(g.footprint("J2"), OVER_PEG)
    assert str(why) == "J2 courtyard sits over a npth (J1)", why


def test_the_pth_severity_does_not_waive_an_npth():
    g, occ = _occ([_pegged(), _front()], {"pth_inside_courtyard": "warning"})
    assert "sits over a npth" in str(occ.legal(g.footprint("J2"), OVER_PEG, by_corners=True))


# a plated lead: J1's pads are through-hole, at 6.6 and 13.4 on y 10; C1 (front, 2 x 1 mm, courtyard 1 mm out) over
# lead 2 with its pads clear of it
LEADED = dict(w=8, h=3, inst="j1", nets=("A", "B"), through=True, face=Face.BACK)
OVER_LEAD = Placement(Location(15.2, 10.0), 0.0, Face.FRONT)


def _small():
    return footprint("C1", 40, 40, w=2, h=1, inst="c1", nets=("C", "D"), excess=1.0)


def test_a_firm_courtyard_over_a_plated_lead_is_refused_at_kicad_s_default_severity():
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()])
    why = occ.legal(g.footprint("C1"), OVER_LEAD, by_corners=True)
    assert str(why) == "C1 courtyard sits over the through-hole lead of J1 pad 2", why


@pytest.mark.parametrize("severity", ["warning", "ignore"])
def test_a_firm_courtyard_over_a_plated_lead_stands_when_the_board_s_severity_is_not_error(severity):
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()], {"pth_inside_courtyard": severity})
    assert occ.legal(g.footprint("C1"), OVER_LEAD, by_corners=True) is None


def test_a_searched_courtyard_keeps_off_a_plated_lead_at_severity_warning():
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()], {"pth_inside_courtyard": "warning"})
    assert "through-hole lead of J1 pad 2" in str(occ.legal(g.footprint("C1"), OVER_LEAD))


def test_the_npth_severity_does_not_waive_a_plated_lead():
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()], {"npth_inside_courtyard": "warning"})
    assert "through-hole lead" in str(occ.legal(g.footprint("C1"), OVER_LEAD, by_corners=True))


def _board(severities=None):
    cfg = Settings(drc_severities=dict(severities or {}))
    return Board(board_geometry([_pegged(cx=40.0, cy=40.0), _front()], width=60, height=60), edge_margin=1.0,
                 settings=cfg)


def test_a_script_s_firm_part_over_an_npth_is_refused_by_default_and_placed_at_severity_warning():
    b = _board()
    b.place(Part("j1"), at=Location(20, 20), face=Face.BACK)
    b.place(Part("j2"), at=Location(20, 20))
    with pytest.raises(PlacementCollision, match=r"J2 courtyard sits over a npth \(J1\)"):
        b.resolve()
    b = _board({"npth_inside_courtyard": "warning"})
    b.place(Part("j1"), at=Location(20, 20), face=Face.BACK)
    b.place(Part("j2"), at=Location(20, 20))
    plan = b.resolve()
    assert plan.placement("j2").location == Location(20, 20)


def test_a_script_s_searched_part_keeps_off_the_npth_at_severity_warning():
    b = _board({"npth_inside_courtyard": "warning"})
    b.place(Part("j1"), at=Location(20, 20), face=Face.BACK)
    b.place(Part("j2"), at=Near(Location(20, 20)))
    plan = b.resolve()
    occ = plan.occupancy
    yards = [s.poly for s in occ.items["J2"].shapes if s.kind == "courtyard"]
    holes = [s.poly for s in occ.items["J1"].shapes if s.kind == "npth"]
    assert yards and holes
    assert not any(polys_overlap(y, h) for y in yards for h in holes)
