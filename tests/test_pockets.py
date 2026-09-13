"""Pocket scan: where a cell or part with nothing placed to pull it could go
at all, found by scanning the free board for rectangles its envelope fits."""
from placemat.occupancy import Occupancy
from placemat.placer import pockets
from placemat.placement import Placement
from placemat.values import Face, Location
from placemat.layout import Board
from placemat.values import Cell, Part
from tests.fixtures import board_geometry, footprint


def test_pockets_are_free_rectangles_the_envelope_fits_in():
    # a 40 x 40 board with a 20 x 40 wall of parts down the middle: two 10-wide strips remain
    fps = [footprint("W%d" % i, 20, 5 + 10 * i, w=20, h=10, inst="w%d" % i, excess=0.0) for i in range(4)]
    fps.append(footprint("R1", 5, 5, w=6, h=3, inst="r1"))
    occ = Occupancy(board_geometry(fps, width=40, height=40), edge_margin=0.0)
    found = pockets(occ, width=6.0, height=3.0, face=Face.FRONT, step=1.0)
    assert found
    for p in found:
        assert p.box.width >= 6.0 and p.box.height >= 3.0
        assert p.box.right <= 10.0 + 1e-9 or p.box.left >= 30.0 - 1e-9       # only the two side strips
    assert found[0].box.area >= found[-1].box.area                            # biggest first


def test_a_cell_with_no_placed_partner_lands_in_a_pocket_and_says_so():
    fps = [footprint("W%d" % i, 20, 5 + 10 * i, w=20, h=10, inst="w%d" % i, nets=("X%d" % i, "Y%d" % i), excess=0.0)
           for i in range(4)]
    fps += [footprint("U1", 60, 60, w=4, h=2, cell="c", inst="c.u", nets=("A", "B")),
            footprint("R1", 60, 63, w=4, h=2, cell="c", inst="c.r", nets=("B", "C"))]
    b = Board(board_geometry(fps, cells=["c"], width=40, height=40), edge_margin=0.0)
    for i in range(4):
        b.place(Part("w%d" % i), at=Location(20, 5 + 10 * i))
    b.place(Cell("c"))                       # nothing it connects to is placed: no seed
    plan = b.resolve()
    box = plan.box("c")
    assert box.right <= 10.0 + 1e-6 or box.left >= 30.0 - 1e-6
    assert "pocket" in plan.step("c").note
    assert not plan.findings


def test_no_pocket_is_a_finding_not_a_crash():
    fps = [footprint("W1", 20, 20, w=40, h=40, inst="w1", excess=0.0),
           footprint("R1", 100, 100, w=6, h=3, inst="r1", nets=("Q", "Z"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.0)
    b.place(Part("w1"), at=Location(20, 20))
    b.place(Part("r1"))
    plan = b.resolve()
    assert any("r1" in f and "pocket" in f for f in plan.findings)
