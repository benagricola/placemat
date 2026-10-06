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
from placemat.values import Beside, Edge, Face, Location, Near, Part, PadRef, Pin, X, Y
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
    why = occ.legal(g.footprint("J2"), OVER_PEG, decided=True)
    assert str(why) == "J2 courtyard sits over a npth (J1)", why


@pytest.mark.parametrize("severity", ["warning", "ignore"])
def test_a_firm_courtyard_over_an_npth_stands_when_the_board_s_severity_is_not_error(severity):
    g, occ = _occ([_pegged(), _front()], {"npth_inside_courtyard": severity})
    assert occ.legal(g.footprint("J2"), OVER_PEG, decided=True) is None


def test_a_firm_part_whose_npth_lies_under_a_placed_courtyard_stands_both_ways():
    g, occ = _occ([_pegged(cx=40.0, cy=40.0), _front(cx=10.0, cy=10.0)], {"npth_inside_courtyard": "warning"})
    over = Placement(Location(10.0, 10.0), 0.0, Face.BACK)
    assert occ.legal(g.footprint("J1"), over, decided=True) is None
    g, occ = _occ([_pegged(cx=40.0, cy=40.0), _front(cx=10.0, cy=10.0)])
    assert "sits over a npth" in str(occ.legal(g.footprint("J1"), over, decided=True))


def test_a_searched_courtyard_keeps_off_an_npth_at_severity_warning():
    g, occ = _occ([_pegged(), _front()], {"npth_inside_courtyard": "warning"})
    why = occ.legal(g.footprint("J2"), OVER_PEG)
    assert str(why) == "J2 courtyard sits over a npth (J1)", why


def test_the_pth_severity_does_not_waive_an_npth():
    g, occ = _occ([_pegged(), _front()], {"pth_inside_courtyard": "warning"})
    assert "sits over a npth" in str(occ.legal(g.footprint("J2"), OVER_PEG, decided=True))


# a plated lead: J1's pads are through-hole, at 6.6 and 13.4 on y 10; C1 (front, 2 x 1 mm, courtyard 1 mm out) over
# lead 2 with its pads clear of it
LEADED = dict(w=8, h=3, inst="j1", nets=("A", "B"), through=True, face=Face.BACK)
OVER_LEAD = Placement(Location(15.2, 10.0), 0.0, Face.FRONT)


def _small():
    return footprint("C1", 40, 40, w=2, h=1, inst="c1", nets=("C", "D"), excess=1.0)


def test_a_firm_courtyard_over_a_plated_lead_is_refused_at_kicad_s_default_severity():
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()])
    why = occ.legal(g.footprint("C1"), OVER_LEAD, decided=True)
    assert str(why) == "C1 courtyard sits over the through-hole lead of J1 pad 2", why


@pytest.mark.parametrize("severity", ["warning", "ignore"])
def test_a_firm_courtyard_over_a_plated_lead_stands_when_the_board_s_severity_is_not_error(severity):
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()], {"pth_inside_courtyard": severity})
    assert occ.legal(g.footprint("C1"), OVER_LEAD, decided=True) is None


def test_a_searched_courtyard_keeps_off_a_plated_lead_at_severity_warning():
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()], {"pth_inside_courtyard": "warning"})
    assert "through-hole lead of J1 pad 2" in str(occ.legal(g.footprint("C1"), OVER_LEAD))


def test_the_npth_severity_does_not_waive_a_plated_lead():
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()], {"npth_inside_courtyard": "warning"})
    assert "through-hole lead" in str(occ.legal(g.footprint("C1"), OVER_LEAD, decided=True))


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


def _yard_clear_of_peg(plan, ref, peg_ref):
    occ = plan.occupancy
    yards = [s.poly for s in occ.items[ref].shapes if s.kind == "courtyard"]
    holes = [s.poly for s in occ.items[peg_ref].shapes if s.kind == "npth"]
    assert yards and holes
    return not any(polys_overlap(y, h) for y in yards for h in holes)


def _peg_at(ref, x, y):
    """A small back part whose unplated peg lies at (x, y)."""
    return dataclasses.replace(footprint(ref, x, y, w=2, h=1, inst=ref.lower(), nets=("P", "Q"), face=Face.BACK),
                               npth=((Location(x, y), PEG),))


def test_a_rider_of_a_searched_host_keeps_off_an_npth_at_severity_warning():
    """The rider stands where placemat put its host: its courtyard keeps off a peg, as the host's own would."""
    def board(extra=(), severities=None):
        fps = [footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("A", "G")),
               footprint("U1", 30, 20, w=8, h=3, inst="u1", nets=("A", "B")),
               footprint("C3", 50, 50, w=8, h=3, inst="c3", nets=("C", "D"))] + list(extra)
        b = Board(board_geometry(fps, width=60, height=60), edge_margin=0.5,
                  settings=Settings(drc_severities=dict(severities or {})))
        b.place(Part("j1"), at=Location(5, 20))        # U1 links to it: the search keeps U1 near
        b.place(Part("u1"))
        # C3's pad 1 4 mm north of U1's pad 1: C3's centre north of U1's
        b.place(Part("c3"), at=Pin(1, X(PadRef(Part("u1"), 1)), Y(PadRef(Part("u1"), 1), -4.0)))
        return b
    alone = board().resolve()
    centre = alone.box("c3").center
    b = board([_peg_at("J9", centre.x, centre.y)], {"npth_inside_courtyard": "warning"})
    b.place(Part("j9"), at=Location(centre.x, centre.y), face=Face.BACK)
    plan = b.resolve()
    assert plan.placement("c3") is not None and "rides u1" in plan.step("c3").note
    assert _yard_clear_of_peg(plan, "C3", "J9")


def test_a_beside_part_stepped_out_from_its_offset_keeps_off_an_npth_at_severity_warning():
    """Blocked at its stated offset, a Beside part is moved out by placemat: it is not stepped onto a peg."""
    def board(extra=(), severities=None):
        fps = [footprint("H1", 20, 20, w=4, h=2, inst="h1", nets=("A", "B")),
               footprint("X1", 50, 50, w=4, h=4, inst="x1", nets=("C", "D"))] + [fp for fp, _ in extra]
        b = Board(board_geometry(fps, width=60, height=60), edge_margin=0.5,
                  settings=Settings(drc_severities=dict(severities or {})))
        b.place(Part("h1"), at=Location(20, 20))
        for fp, face in extra:
            b.place(Part(fp.inst), at=Location(fp.location.x, fp.location.y), face=face)
        b.place(Part("x1"), at=Beside(Part("h1"), Edge.EAST))
        return b
    x0 = board().resolve().box("x1").center.x
    # a front part whose courtyard reaches 0.5 mm into X1's at the offset, south of H1: X1 steps out east past it
    blocker = (footprint("B1", x0 - 2.7, 22.0, w=2, h=1, inst="b1", nets=("E", "F")), Face.FRONT)

    def blocked(extra=(), severities=None):
        return board([blocker] + list(extra), severities)
    stepped = blocked().resolve()
    x1 = stepped.box("x1").center.x
    assert x0 < x1 < x0 + 1.0, (x0, x1)
    # a peg under the west of X1's courtyard where it was stepped out to, clear of its pads, H1 and B1
    peg = (x1 - 1.6, 18.5)
    plan = blocked([(_peg_at("J9", *peg), Face.BACK)], {"npth_inside_courtyard": "warning"}).resolve()
    assert plan.box("x1").center.x > x1
    assert _yard_clear_of_peg(plan, "X1", "J9")
