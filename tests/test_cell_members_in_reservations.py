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
    assert why is not None and "L1" in str(why) and "1.8 mm" in str(why) and "C1" not in str(why), why


def test_a_named_member_does_not_admit_the_others():
    g, occ = _occ()
    occ.reserve(Box(12.5, 5, 15.5, 15), "the feed", owners=("C1",))
    assert occ.legal(g.cells["k"], AT) is None
    occ.reserve(Box(12.5, 5, 30, 15), "the feed", owners=("C1",))
    why = occ.legal(g.cells["k"], AT)
    assert why is not None and "C2" in str(why), why


def test_a_members_net_admits_no_member():
    """An allowed net lets copper through, not the parts that carry it."""
    g, occ = _occ()
    occ.reserve(Box(12.5, 5, 30, 15), "the feed", allow=("C",))
    why = occ.legal(g.cells["k"], AT)
    assert why is not None and "C1" in str(why), why


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


def _with_track(net="D"):
    """The cell with a track of its own between C1 and C2."""
    from placemat.occupancy import Shape
    from placemat.values import CopperLayer
    from tests.fixtures import rect
    g, occ = _occ()
    poly = rect(16.0, 10.0, 2.0, 0.3)
    occ.add_copper([Shape("k", "copper", frozenset([Face.FRONT]), frozenset([CopperLayer.F]), net, poly, Box.of_points(poly))])
    return g, occ


def test_a_cells_own_track_has_no_height():
    g, occ = _with_track()
    occ.reserve(Box(12.5, 5, 30, 15), "a height band", admitted=LOW)
    assert occ.legal(g.cells["k"], AT) is None


def test_a_cells_own_track_on_an_allowed_net_is_let_through():
    g, occ = _with_track("D")
    occ.reserve(Box(15.2, 5, 16.8, 15), "the feed", allow=("D",))
    assert occ.legal(g.cells["k"], AT) is None


def test_a_cells_own_track_elsewhere_is_named_as_its_copper():
    g, occ = _with_track("D")
    occ.reserve(Box(15.2, 5, 16.8, 15), "the gap")
    why = occ.legal(g.cells["k"], AT)
    assert why is not None and "its own copper" in str(why) and "L1" not in str(why), why


def test_the_sweep_counts_each_refused_member_as_its_own():
    """A band two members cross in turn as the cell slides: the sweep keeps a
    refusal (and a blocker) per member, each saying which, as legal() does."""
    pytest.importorskip("placemat_native")
    g, occ = _occ()
    occ.reserve(Box(12.8, 5, 13.2, 15), "a narrow band")
    cell = g.cells["k"]
    others = occ.obstacles(occ._geometry(cell))
    sweep = occ.native_sweeper(cell, Face.FRONT, [0.0], others, None)
    triples = [(8.0 + 0.5 * i, 10.0, 0) for i in range(30)]
    _, _, refused = sweep.run(triples, False)
    said = {reason() for _, _, _, reason, _ in refused}
    assert any("member L1" in str(s) for s in said) and any("member C1" in str(s) for s in said), said
    blockers = {b[1] for *_, b in refused}
    assert any("L1" in str(o) for o in blockers) and any("C1" in str(o) for o in blockers), blockers
    for _, _, first, reason, blocker in refused:
        x, y, _ = triples[first]
        blame = []
        assert reason() == occ.legal(cell, Placement(Location(x, y), 0.0, Face.FRONT), others=list(others), blame=blame)
        assert blame[0].owner == blocker[1]


def _keepout_over_own_track(excludes):
    """Cell k: U1, which the keepout allows by name, and S1, which it does
    not, both outside it, and a track of the cell's own on F.Cu inside it."""
    from placemat.board_geometry import CopperItem
    from placemat.cutouts import Circle
    from placemat.layout import Board
    from placemat.values import Cell, CopperLayer, Part
    from tests.fixtures import rect
    poly = rect(26.0, 20.0, 3.0, 0.3)
    track = CopperItem("track", "B", frozenset([CopperLayer.F]), (poly,), Box.of_points(poly), "k", 0.3)
    fps = [footprint("U1", 20, 20, w=2, h=1, inst="k.u1", cell="k", nets=("A", "B")),
           footprint("S1", 20, 24, w=2, h=1, inst="k.s1", cell="k", nets=("C", "D"))]
    b = Board(board_geometry(fps, cells=["k"], copper=[track], width=50, height=50), edge_margin=0.5,
              keep_going=True)
    b.keepout(Circle(2.0), "roof", at=Location(26, 20), excludes=excludes, layers=(CopperLayer.F,),
              allow=(Part("k.u1"),), why="low parts only")
    centre = b.geometry.cells["k"].box.center
    b.place(Cell("k"), at=Location(centre.x, centre.y))
    return b.resolve()


def test_a_parts_only_keepout_leaves_a_cells_own_copper_be():
    """It keeps parts out; copper is not what it excludes."""
    plan = _keepout_over_own_track(("parts",))
    assert not [f for f in plan.findings if "own copper" in f], list(plan.findings)


def test_a_keepout_of_tracks_still_judges_a_cells_own_copper():
    plan = _keepout_over_own_track(("parts", "tracks"))
    assert [f for f in plan.findings if "own copper" in f], list(plan.findings)
