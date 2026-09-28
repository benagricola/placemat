"""A cell placed on the back mirrors and turns its members with it; a
member's recorded placement must say where its own shapes went, or what is
moved from it (its airwire ends, its courtyard under the physical envelope,
a via at its pad) lands elsewhere. A member read at 90 degrees showed it."""
import pytest

from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint


def _board(envelope):
    import dataclasses
    # the part's origin off its body's centre, as a real footprint's often is: a half turn shows
    c1 = footprint("C1", 30, 30, w=4, h=2, rotation=90.0, cell="k", excess=0.5, fab=(28.0, 29.0, 32.0, 31.0))
    fps = [dataclasses.replace(c1, location=Location(28.5, 30.0)),
           footprint("R2", 36, 30, w=2, h=1, cell="k", fab=(35.0, 29.5, 37.0, 30.5)),
           footprint("J1", 10, 50, w=4, h=2, nets=("X", "Y"), through=True, fab=(8.0, 49.0, 12.0, 51.0))]
    g = board_geometry(fps, cells=("k",), width=60, height=60)
    return g, Occupancy(g, edge_margin=0.0, settings=Settings(place_envelope=envelope))


@pytest.mark.parametrize("face, rotation", [(Face.BACK, 0.0), (Face.BACK, 90.0), (Face.FRONT, 90.0)])
def test_a_members_airwire_ends_stay_on_its_pads(face, rotation):
    g, occ = _board("courtyard")
    occ.commit(g.cells["k"], Placement(Location(20.0, 20.0), rotation, face))
    for n in ("1", "2"):
        a, p = occ.pad_anchor("C1", n), occ.pad_location("C1", n)
        assert abs(a.x - p.x) < 1e-6 and abs(a.y - p.y) < 1e-6, (n, a, p)


def test_a_flipped_members_yard_is_its_courtyard():
    g, phys = _board("physical")
    _, union = _board("union")
    at = Placement(Location(20.0, 20.0), 0.0, Face.BACK)
    phys.commit(g.cells["k"], at)
    union.commit(union.geometry.cells["k"], at)
    court = next(s for s in union.items["C1"].shapes if s.kind == "courtyard")
    yard = phys._yard("C1")
    assert yard.box == pytest.approx(court.box, abs=1e-6), (yard.box, court.box)
