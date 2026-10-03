"""What a scan of a big cell asks of the occupancy is answered without moving every member box for every candidate: the
member boxes are moved when read, a reservation far from a box is rejected before any rounding, and the empty
occupancy a measure needs is built once. None of it changes an answer."""
import random

from placemat.occupancy import Occupancy, _ShiftedBoxes, _shift_box
from placemat.placement import Placement
from placemat.values import Box, Face, Location
from tests.fixtures import board_geometry, footprint


def _cell_board():
    fps = [footprint("R%d" % k, 10 + 3 * k, 10, w=2, h=1, nets=("A%d" % k, "B%d" % k), cell="k") for k in range(12)]
    return board_geometry(fps, cells=("k",), width=80, height=60)


def test_moved_member_boxes_equal_the_eager_list_and_are_moved_when_read():
    rnd = random.Random(7)
    origin = [None if k % 5 == 0 else Box(rnd.uniform(-9, 0), rnd.uniform(-9, 0), rnd.uniform(0.1, 9), rnd.uniform(0.1, 9))
              for k in range(40)]
    for dx, dy in ((0.0, 0.0), (12.3456789012, -4.0000000004), (0.1 + 0.2, 7.0)):
        eager = [_shift_box(b, dx, dy) for b in origin]
        lazy = _ShiftedBoxes(origin, dx, dy)
        assert len(lazy) == len(eager) and list(lazy) == eager and lazy[-1] == eager[-1]
        assert [lazy[k] for k in (7, 3, 7)] == [eager[7], eager[3], eager[7]]


def test_a_box_that_could_overlap_a_region_is_never_rejected_early():
    rnd = random.Random(11)
    region = Box(5.0, 5.0, 9.0, 8.0)
    for _ in range(4000):
        b = Box(rnd.uniform(-5, 12), rnd.uniform(-5, 12), 0.0, 0.0)
        b = Box(b.left, b.top, b.left + rnd.uniform(0.0, 4), b.top + rnd.uniform(0.0, 4))
        dx, dy = round(rnd.uniform(-3, 3), rnd.choice([1, 3, 9])), round(rnd.uniform(-3, 3), rnd.choice([1, 3, 9]))
        moved = _ShiftedBoxes([b], dx, dy)
        if region.overlaps(moved[0]):
            assert moved.could_overlap(0, region)
    touching = _ShiftedBoxes([Box(0.0, 0.0, 1.0, 1.0)], 9.0 + 5e-10, 5.0)      # a hair off the region's edge
    assert touching.could_overlap(0, region)


def test_the_empty_occupancy_of_a_measure_is_built_once_unless_a_fresh_one_is_asked_for():
    from placemat.layout import Board
    b = Board(_cell_board(), edge_margin=0.5)
    first = b._bare_occupancy()
    assert b._bare_occupancy() is first
    assert b._bare_occupancy(fresh=True) is not first
    fp = b.geometry.footprint("R0")
    cached = b.envelope(fp, 90.0)
    occ = b._bare_occupancy(fresh=True)
    g = occ._geometry(fp)
    from placemat.geometry import transform_box
    t = occ._transform(g, Placement(Location(0.0, 0.0), 90.0, Face.FRONT))
    assert cached == Box.union([transform_box(s.box, t) for s in g.shapes if s.kind != "npth"])
    b.edge_margin = 0.25
    assert b._bare_occupancy() is not first


def test_a_cell_is_judged_against_a_reservation_by_the_members_it_overlaps():
    g = _cell_board()
    occ = Occupancy(g, edge_margin=0.0)
    cell = g.cells["k"]
    at = occ._geometry(cell).reference
    occ.reserve(Box(100, 100, 110, 110), "far away")
    assert occ.legal(cell, at) is None
    occ.reserve(Box(20.5, 9.0, 23.0, 11.0), "over R3 and R4")
    why = occ.legal(cell, Placement(at.location, at.rotation, Face.FRONT))
    assert why is not None and "over R3 and R4" in str(why)
    moved = Placement(Location(at.location.x, at.location.y + 20.0), at.rotation, Face.FRONT)
    assert occ.legal(cell, moved) is None
