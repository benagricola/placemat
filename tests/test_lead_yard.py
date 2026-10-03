"""Under the physical envelope a drawn part claims its pads, mask, silk and
body, not its courtyard; KiCad's DRC still refuses a courtyard over another
part's plated lead (pth_inside_courtyard), so placemat keeps that one rule:
a courtyard off another part's lead, both ways."""
import re

import pytest

from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint

# the through-hole part: leads 1 and 2 at x 8.6 and 11.4 (1 x 1 mm), body 8..12
LEADED = dict(w=4, h=2, nets=("A", "B"), through=True, fab=(8.0, 9.0, 12.0, 11.0))
# a spot for a 2 x 1 mm part whose body clears lead 2 by 0.6 mm and the leaded body by 0.5
SPOT = Placement(Location(13.5, 10.0), 0.0, Face.FRONT)


def _small(ref="C1", excess=1.0, cell=None, cx=30.0):
    return footprint(ref, cx, 30, w=2, h=1, nets=("C", "D"), excess=excess, cell=cell,
                     fab=(cx - 1.0, 29.5, cx + 1.0, 30.5))


def _occ(fps, envelope="physical", cells=()):
    g = board_geometry(fps, cells=cells, width=60, height=60)
    return g, Occupancy(g, edge_margin=0.0, settings=Settings(place_envelope=envelope))


def test_a_courtyard_is_kept_off_a_placed_parts_plated_lead():
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small()])
    why = occ.legal(g.footprint("C1"), SPOT)
    assert str(why) == "C1 courtyard sits over the through-hole lead of J1 pad 2", why


def test_a_plated_lead_is_kept_out_from_under_a_placed_parts_courtyard():
    leaded = dict(LEADED, fab=(28.0, 39.0, 32.0, 41.0))         # drawn where the part stands
    g, occ = _occ([footprint("J1", 30, 40, **leaded), footprint("C1", 13.5, 10, w=2, h=1, nets=("C", "D"),
                                                                  excess=1.0, fab=(12.5, 9.5, 14.5, 10.5))])
    blame = []
    why = occ.legal(g.footprint("J1"), Placement(Location(10.0, 10.0), 0.0, Face.FRONT), blame=blame)
    assert str(why) == "C1 courtyard sits over the through-hole lead of J1 pad 2", why
    assert [b.kind for b in blame] == ["courtyard"]


def test_a_courtyard_clear_of_the_lead_may_sit_there():
    g, occ = _occ([footprint("J1", 10, 10, **LEADED), _small(excess=0.1)])
    assert occ.legal(g.footprint("C1"), SPOT) is None


def test_a_parts_own_lead_under_its_own_courtyard_is_its_own():
    g, occ = _occ([footprint("J1", 30, 30, **dict(LEADED, fab=(28.0, 29.0, 32.0, 31.0)))])
    assert occ.legal(g.footprint("J1"), Placement(Location(10.0, 10.0), 0.0, Face.FRONT)) is None


def test_a_board_without_plated_leads_keeps_no_courtyards():
    g, occ = _occ([footprint("R1", 10, 10, w=4, h=2, fab=(8.0, 9.0, 12.0, 11.0)), _small()])
    assert not occ._yard_refs
    assert occ.legal(g.footprint("C1"), SPOT) is None


def test_a_cell_member_keeps_its_courtyard_off_a_lead():
    fps = [footprint("J1", 10, 10, **LEADED), _small(cell="k"), _small("R2", excess=0.1, cell="k", cx=33.0)]
    g, occ = _occ(fps, cells=("k",))
    # the cell's box runs 29..34 round centre 31.5: C1 lands at 13.5 when the centre is at 15
    why = occ.legal(g.cells["k"], Placement(Location(15.0, 10.0), 0.0, Face.FRONT))
    assert why is not None and "courtyard sits over the through-hole lead of J1 pad 2" in str(why), why


def test_a_courtyard_envelope_refusal_names_the_pad_too():
    g, occ = _occ([footprint("U1", 10, 10, w=4, h=2, nets=("A", "B"), through=True),
                   footprint("R1", 30, 30, w=2, h=1, nets=("B", "C"), face=Face.BACK)], envelope="courtyard")
    why = occ.legal(g.footprint("U1"), Placement(Location(30.0, 30.0), 0.0, Face.FRONT))
    assert why is not None and re.search(r"R1 courtyard sits over the through-hole lead of U1 pad [12]", str(why)), why


def test_the_native_index_and_the_python_scan_agree_round_a_lead():
    pytest.importorskip("placemat_native")
    for placed, searched in (("J1", "C1"), ("C1", "J1")):
        g, occ = _occ([footprint("J1", 10, 10, **LEADED), footprint("C1", 13.5, 10, w=2, h=1, nets=("C", "D"),
                                                                      excess=1.0, fab=(12.5, 9.5, 14.5, 10.5))])
        item = g.footprint(searched)
        geom = occ._geometry(item)
        native = occ.obstacles(geom)
        plain = list(native)
        assert getattr(native, "_native", None) is not None
        centre = (13.5, 10.0) if searched == "C1" else (10.0, 10.0)
        refused = 0
        for i in range(-12, 13):
            for j in range(-4, 5):
                p = Placement(Location(centre[0] + i * 0.1, centre[1] + j * 0.25), 0.0, Face.FRONT)
                a = occ.legal(item, p, others=native)
                b = occ.legal(item, p, others=plain)
                assert (a is None) == (b is None), (searched, p, a, b)
                refused += a is not None and "through-hole lead" in str(a)
        assert refused, searched


def test_a_satellite_keeps_its_courtyard_off_its_anchors_lead():
    """A block's members are judged against each other inside the block
    (both are pending in a resolve): the lead rule holds there too."""
    from placemat.placer import BlockSpec, layout_block
    anchor = footprint("J1", 20, 20, w=4, h=2, inst="j1", nets=("VOUT", "VIN"), through=True,
                       fab=(18.0, 19.0, 22.0, 21.0))
    sat = footprint("C1", 40, 20, w=2, h=1, inst="c1", nets=("VIN", "GND"), excess=1.0, fab=(39.0, 19.5, 41.0, 20.5))
    g, occ = _occ([anchor, sat])
    occ.pending |= {"J1", "C1"}
    at = Placement(Location(20, 20), 0.0, Face.FRONT)
    members, why = layout_block(occ, BlockSpec(g.footprint("j1"), ((g.footprint("c1"), "VIN"),), gap=0.3), at)
    assert members is None and "no legal spot" in str(why), why          # too tight a gap for its courtyard
    members, why = layout_block(occ, BlockSpec(g.footprint("j1"), ((g.footprint("c1"), "VIN"),), gap=None), at)
    assert members is not None, why
    occ.commit(g.footprint("j1"), members["j1"])
    assert occ.legal(g.footprint("c1"), members["c1"]) is None
