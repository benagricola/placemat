"""A cell meets a reservation member by member: each member is let in by its
own name, its own nets or its own height, and the cell is refused only when
a member that is not has its body over the region. A rigid cell may cross a
height band with its low members; one named member no longer admits the
rest."""
import pytest

from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Box, Face, Location
from tests.fixtures import board_geometry, footprint

AT = Placement(Location(14.0, 10.0), 0.0, Face.FRONT)      # the cell where it was read: its box runs 9..19


def _occ():
    fps = [footprint("L1", 10, 10, w=2, h=2, nets=("A", "B"), cell="k", fields={"Pm.Height": "1.8"}),
           footprint("C1", 14, 10, w=2, h=1, nets=("C", "D"), cell="k", fields={"Pm.Height": "0.5"}),
           footprint("C2", 18, 10, w=2, h=1, nets=("E", "F"), cell="k", fields={"Pm.Height": "0.5"})]
    g = board_geometry(fps, cells=("k",), width=60, height=60)
    occ = Occupancy(g, edge_margin=0.0)
    return g, occ


LOW = frozenset({"C1", "C2"})


def test_a_cell_crosses_a_height_band_with_its_low_members():
    g, occ = _occ()
    occ.reserve(Box(12.5, 5, 30, 15), "a height band", admitted=LOW)
    assert occ.legal(g.cells["k"], AT) is None


def test_its_tall_member_in_the_band_is_refused_and_named():
    g, occ = _occ()
    occ.reserve(Box(8, 5, 30, 15), "a height band", admitted=LOW)
    why = occ.legal(g.cells["k"], AT)
    assert why is not None and "L1" in why and "1.8 mm" in why and "C1" not in why, why


def test_a_named_member_does_not_admit_the_others():
    g, occ = _occ()
    occ.reserve(Box(12.5, 5, 15.5, 15), "the feed", owners=("C1",))
    assert occ.legal(g.cells["k"], AT) is None
    occ.reserve(Box(12.5, 5, 30, 15), "the feed", owners=("C1",))
    why = occ.legal(g.cells["k"], AT)
    assert why is not None and "C2" in why, why


def test_a_members_net_does_not_admit_the_others():
    g, occ = _occ()
    occ.reserve(Box(12.5, 5, 30, 15), "the feed", allow=("C",))
    why = occ.legal(g.cells["k"], AT)
    assert why is not None and "C2" in why, why


def test_every_member_named_admits_the_cell():
    g, occ = _occ()
    occ.reserve(Box(8, 5, 30, 15), "the module's own", owners=("L1", "C1", "C2"))
    assert occ.legal(g.cells["k"], AT) is None


@pytest.mark.parametrize("region, kw", [
    (Box(12.5, 5, 30, 15), {"admitted": LOW}),
    (Box(8, 5, 30, 15), {"admitted": LOW}),
    (Box(12.5, 5, 30, 15), {"owners": ("C1",)}),
    (Box(12.5, 5, 30, 15), {"allow": ("C",)}),
], ids=["low-in-band", "tall-in-band", "named", "net"])
def test_the_native_sweep_refuses_the_same_spots(region, kw):
    pytest.importorskip("placemat_native")
    g, occ = _occ()
    occ.reserve(region, "a region", **kw)
    cell = g.cells["k"]
    geom = occ._geometry(cell)
    others = occ.obstacles(geom)
    sweep = occ.native_sweeper(cell, Face.FRONT, [0.0], others, None)
    assert sweep is not None
    triples = [(8.0 + 0.5 * i, 10.0, 0) for i in range(30)]
    legal, _, refused = sweep.run(triples, False)
    python = [i for i, (x, y, _) in enumerate(triples)
              if occ.legal(cell, Placement(Location(x, y), 0.0, Face.FRONT), others=list(others)) is None]
    assert list(legal) == python
    for _, _, first, reason, _ in refused:
        x, y, _ = triples[first]
        assert reason() == occ.legal(cell, Placement(Location(x, y), 0.0, Face.FRONT), others=list(others))
